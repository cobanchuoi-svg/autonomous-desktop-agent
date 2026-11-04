"""LLM primary router and narrowly scoped Gemini CLI clarification fallback."""

import json
import re
from typing import Any, Optional

from agent.workflows.models import WorkflowRequest
from agent.workflows.registry import WorkflowRegistry


class WorkflowRouter:
    SYSTEM_PROMPT = """You are the primary intent router for a local desktop agent. Choose exactly one workflow from the supplied registry and extract only its parameters. Never invent workflows, tools, capabilities, or results. Do not execute anything. If essential information is missing, return status CLARIFY with one concise question. If no registered workflow can handle the request, return status NO_MATCH. Otherwise return status MATCH. Output one JSON object only: {\"status\":\"MATCH|CLARIFY|NO_MATCH\",\"workflow\":\"registered name or NO_MATCH\",\"confidence\":0.0,\"parameters\":{},\"clarification_question\":null}. Confidence is a rough routing estimate, not proof. Use FSM_TASK for complex desktop goals supported by the existing FSM. For multi-step requests use WORKFLOW_CHAIN with ordered steps [{\"workflow\":\"registered name\",\"parameters\":{...}}]. Never nest WORKFLOW_CHAIN. Do not choose a workflow until its required parameters are present."""

    def __init__(self, provider: Any, registry: WorkflowRegistry, fallback: Any = None):
        self.provider = provider
        self.registry = registry
        self.fallback = fallback

    async def route(self, message: str) -> WorkflowRequest:
        language_request = self._resolve_language_preference(message)
        if language_request is not None:
            return language_request

        # Fast path 1: Explicit app launch (e.g. "mở chrome", "open notepad") runs instantly in 0.001s locally
        local_app_route = self._resolve_explicit_app_launch(message)
        if local_app_route is not None:
            return local_app_route

        # Fast path 2: Explicit search
        dummy_req = WorkflowRequest("NO_MATCH", 0.0, {})
        local_search_route = self._resolve_explicit_web_search(message, dummy_req)
        if local_search_route is not None:
            return local_search_route

        prompt = f"Available workflows:\n{self.registry.descriptions()}\n\nUser request:\n{message}\n\nReturn JSON now."
        try:
            raw = await self.provider.generate(prompt, system_prompt=self.SYSTEM_PROMPT, json_mode=True)
            primary = self._parse_response(raw, source=getattr(self.provider, "provider_name", "llm"))
        except Exception as exc:
            primary = WorkflowRequest("NO_MATCH", 0.0, {}, "NO_MATCH", None, getattr(self.provider, "provider_name", "llm"), str(exc))

        local_desktop_task = self._resolve_explicit_document_task(message, primary)
        if local_desktop_task is not None:
            return local_desktop_task
        local_text_request = self._resolve_explicit_text_generation(message, primary)
        if local_text_request is not None:
            return local_text_request
        local_chat = self._resolve_explicit_chat(message, primary)
        if local_chat is not None:
            return local_chat
        should_fallback = primary.status in {"CLARIFY", "NO_MATCH"}
        if not should_fallback or self.fallback is None:
            return primary
        try:
            return await self.fallback.resolve(message, primary)
        except Exception as exc:
            return WorkflowRequest(
                workflow=primary.workflow,
                confidence=primary.confidence,
                parameters=primary.parameters,
                status=primary.status,
                clarification_question=primary.clarification_question,
                router_source=getattr(self.provider, "provider_name", "llm"),
                fallback_error=str(exc),
            )

    def _resolve_explicit_app_launch(self, message: str, primary: Optional[WorkflowRequest] = None) -> Optional[WorkflowRequest]:
        """Fill OPEN_APP slots from an unambiguous local launch phrase before cloud fallback."""
        if primary is not None:
            if primary.status not in {"CLARIFY", "NO_MATCH"}:
                return None
            if primary.workflow not in {"OPEN_APP", "CLARIFY", "NO_MATCH"}:
                return None
        from agent.decision.goal_classifier import GoalClassifier

        classification = GoalClassifier().classify(message)
        app_name = (
            classification.application[0].strip()
            if classification.category.value == "OPEN_APP" and classification.application
            else ""
        )
        if not app_name:
            # Small multilingual phrase catalog for explicit, launch-only requests.
            match = re.match(
                r"^\s*(?:please\s+)?(?:mở|bật|khởi\s+chạy|open|launch|start|run)\s+(.+?)\s*[.!?]*\s*$",
                message,
                flags=re.IGNORECASE,
            )
            if not match:
                return None
            candidate = match.group(1).strip()
            if re.search(
                r"\b(?:and|then|search|find|write|describe|type|into|in|to)\b|và|rồi|sau\s+đó|tìm|viết|tả|soạn|nhập|vào",
                candidate,
                flags=re.IGNORECASE,
            ):
                return None
            app_name = candidate
        if not app_name:
            return None
        conf = max(getattr(primary, "confidence", 0.0), classification.confidence, 0.95)
        return WorkflowRequest(
            "OPEN_APP", conf,
            {"app_name": app_name}, "MATCH", None, "local_rule",
        )

    def _resolve_explicit_web_search(self, message: str, primary: WorkflowRequest) -> Optional[WorkflowRequest]:
        """Extract an explicit search query locally when primary router omitted the query slot."""
        if primary.status not in {"CLARIFY", "NO_MATCH"}:
            return None
        if primary.workflow not in {"WEB_SEARCH", "CLARIFY", "NO_MATCH"}:
            return None
        text = re.sub(r"\s+", " ", message.strip())
        text = re.sub(r"[?.!]+$", "", text).strip()
        patterns = (
            r"^(?:please\s+)?(?:search(?:\s+for)?|look\s+up|google)\s+(.+)$",
            r"^(?:please\s+)?(?:tìm\s+kiếm|tìm|tra\s+cứu)\s+(.+)$",
        )
        query = None
        for pattern in patterns:
            match = re.match(pattern, text, flags=re.IGNORECASE)
            if match:
                query = match.group(1).strip()
                break
        if not query:
            return None
        query = re.sub(
            r"\s+(?:in|on|using|with)\s+(?:google\s+)?(?:chrome|edge|browser|google)\s*$",
            "", query, flags=re.IGNORECASE,
        ).strip()
        query = re.sub(r"\s+(?:trên|bằng)\s+(?:chrome|edge|trình\s+duyệt|google)\s*$", "", query, flags=re.IGNORECASE).strip()
        if not query or len(query) > 500:
            return None
        return WorkflowRequest(
            "WEB_SEARCH", max(primary.confidence, 0.95),
            {"query": query}, "MATCH", None, "local_rule",
        )

    def _resolve_explicit_document_task(self, message: str, primary: WorkflowRequest) -> Optional[WorkflowRequest]:
        """Route explicit app-plus-writing requests to the single-draft writer."""
        text = re.sub(r"\s+", " ", message.strip())
        active_document_patterns = (
            r"^(?:please\s+)?(?:write|type|draft|compose|describe|viết|soạn|tả|miêu\s+tả|mô\s+tả)\s+"
            r"(?:the\s+)?(?:open|current|active)\s+(?:document|file)\s*[,;:]?\s*(.+)$",
            r"^(?:in|inside|within)\s+(?:the\s+)?(?:open|current|active)\s+(?:document|file)\s*[,;:]?\s*(.+)$",
            r"^(?:please\s+)?(.+?)\s+(?:in|into|to)\s+(?:the\s+)?(?:open|current|active)\s+(?:document|file)\s*[.!?]*$",
            r"^(?:trong\s+)?(?:tài\s+liệu|văn\s+bản)\s+đang\s+mở\s*[,;:]?\s*(.+)$",
            r"^(?:hãy\s+)?(.+?)\s+(?:vào|trong)\s+(?:tài\s+liệu|văn\s+bản)\s+đang\s+mở\s*[.!?]*$",
        )
        for pattern in active_document_patterns:
            active_match = re.match(pattern, text, flags=re.IGNORECASE)
            if not active_match:
                continue
            instruction = active_match.group(1).strip()
            if re.search(
                r"\b(?:write|type|draft|compose|describe)\b|viết|soạn|tả|miêu\s+tả|mô\s+tả",
                instruction,
                flags=re.IGNORECASE,
            ):
                return WorkflowRequest(
                    "WRITE_TEXT_TO_APP", max(primary.confidence, 0.95),
                    {"target_app": "__active_document__", "instruction": instruction},
                    "MATCH", None, "local_rule",
                )

        match = re.match(
            r"^(?:please\s+)?(?:mở|open|launch|start)\s+(.+?)\s+"
            r"(?:vào|into|then|rồi|và|and|sau\s+đó|and\s+then)\s+(.+?)\s*[.!?]*\s*$",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        app_name, instruction = (part.strip() for part in match.groups())
        if not app_name or len(app_name) > 80 or not instruction:
            return None
        if not re.search(
            r"\b(?:write|type|enter|edit|describe|draft|compose)\b|viết|soạn|nhập|tả|miêu\s+tả|mô\s+tả",
            instruction,
            flags=re.IGNORECASE,
        ):
            return None
        if not re.search(
            r"\b(?:wps|word|document\w*|docx|writer|notepad|editor|docs|vs\s+code|vscode|code\s+editor)\b|visual\s+studio\s+code|tài\s+liệu|văn\s+bản",
            app_name,
            flags=re.IGNORECASE,
        ):
            return None

        description = re.match(
            r"^(?:tả|miêu\s+tả|mô\s+tả|describe)\s+"
            r"(?:(?:một|1|a|an)\s+)?(?:đoạn\s+văn|paragraph)\s+(?:về|about)\s+(.+)$",
            instruction,
            flags=re.IGNORECASE,
        )
        if description:
            topic = description.group(1).strip()
            if re.match(r"^(?:tả|miêu\s+tả|mô\s+tả)", instruction, flags=re.IGNORECASE):
                instruction = f"Viết một đoạn văn miêu tả {topic}."
            else:
                instruction = f"Write a descriptive paragraph about {topic}."
        else:
            description = re.match(r"^(?:tả|miêu\s+tả|mô\s+tả)\s+(.+)$", instruction, flags=re.IGNORECASE)
            if description:
                instruction = f"Viết một đoạn văn miêu tả {description.group(1)}."
        title_match = re.search(
            r"\b(?:document|file|tài\s+liệu)\s+([\w-]+)", text, flags=re.IGNORECASE,
        )
        params = {"target_app": app_name, "instruction": instruction}
        if title_match:
            params["window_title"] = title_match.group(1)
            title = re.escape(title_match.group(1))
            instruction = re.sub(
                rf"^\s*(?:open|mở|into|vào)?\s*{title}\s*(?:(?:and|và|then|rồi)\s+)?",
                "", instruction, flags=re.IGNORECASE,
            ).strip()
            params["instruction"] = instruction or message.strip()
        return WorkflowRequest(
            "WRITE_TEXT_TO_APP", max(primary.confidence, 0.95),
            params, "MATCH", None, "local_rule",
        )

    def _resolve_explicit_text_generation(self, message: str, primary: WorkflowRequest) -> Optional[WorkflowRequest]:
        """Route clear standalone writing requests to the registered text generator."""
        if primary.status not in {"CLARIFY", "NO_MATCH"}:
            return None
        text = message.strip()
        match = re.match(
            r"^\s*(?:please\s+|hãy\s+)?(?:write|draft|compose|describe|viết|soạn|tả|miêu\s+tả|mô\s+tả)\s+(.+?)\s*[.!?]*\s*$",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        instruction = text
        return WorkflowRequest(
            "GENERATE_TEXT", max(primary.confidence, 0.9),
            {"instruction": instruction}, "MATCH", None, "local_rule",
        )

    def _resolve_explicit_chat(self, message: str, primary: WorkflowRequest) -> Optional[WorkflowRequest]:
        """Keep ordinary questions in CHAT when the model returns an invalid route."""
        if primary.status not in {"CLARIFY", "NO_MATCH"}:
            return None
        text = message.strip()
        if not text:
            return None
        action_words = re.search(
            r"\b(?:open|launch|start|run|search|find|click|tap|type|write|press|edit)\b"
            r"|mở|bật|khởi\s+chạy|tìm|tra\s+cứu|nhấn|bấm|viết|soạn|nhập",
            text,
            flags=re.IGNORECASE,
        )
        if action_words:
            return None
        english_question = re.match(
            r"^(?:what|who|where|when|why|how|is|are|do|does|did|can)\b",
            text,
            flags=re.IGNORECASE,
        )
        vietnamese_question = re.search(
            r"(?:\?|\b(?:à|hả|sao|gì|nào|không|chưa))\s*[.!?]*$",
            text,
            flags=re.IGNORECASE,
        )
        greetings = re.match(
            r"^\s*(?:hi|hello|hey|chào|chao|alo|hế lô|hé lô|ê\b|ơi\b|good\s+(?:morning|afternoon|evening))\b",
            text,
            flags=re.IGNORECASE,
        )
        if not (english_question or vietnamese_question or greetings):
            return None
        return WorkflowRequest(
            "CHAT", max(primary.confidence, 0.9),
            {"message": text}, "MATCH", None, "local_rule",
        )

    @staticmethod
    def _resolve_language_preference(message: str) -> Optional[WorkflowRequest]:
        """Recognize an explicit language preference without asking the LLM router."""
        text = message.strip()
        vietnamese = re.search(
            r"\b(?:use|speak|reply|answer|respond)\s+(?:in\s+)?vietnamese\b"
            r"|(?:dùng|dung|nói|noi|trả\s+lời|tra\s+loi|hãy\s+dùng|hay\s+dung)\s+"
            r"(?:(?:bằng|bang)\s+)?(?:tiếng|tieng)\s+việt\b",
            text,
            flags=re.IGNORECASE,
        )
        if not vietnamese:
            return None
        return WorkflowRequest(
            "CHAT", 1.0,
            {"message": text, "language": "Vietnamese"},
            "MATCH", None, "local_rule",
        )

    def _parse_response(self, raw: str, *, source: str) -> WorkflowRequest:
        obj = self._extract_object(raw)
        status = str(obj.get("status", "MATCH")).strip().upper()
        if status in {"MATCH", "CLARIFY", "NO_MATCH"} and obj.get("workflow") is None:
            status_as_workflow = str(obj.get("result", "")).strip().upper()
            if status_as_workflow in {"MATCH", "CLARIFY", "NO_MATCH"}:
                status = status_as_workflow
        name = obj.get("workflow", obj.get("selected_workflow", obj.get("intent", "NO_MATCH")))
        default_confidence = 0.5 if source == "gemini_cli" else 0.0
        confidence = obj.get("confidence", default_confidence)
        if isinstance(confidence, str):
            try:
                confidence = float(confidence)
            except ValueError:
                confidence = default_confidence
        parameters = obj.get("parameters", obj.get("params", obj.get("arguments", {})))
        if isinstance(parameters, str):
            try:
                parameters = json.loads(parameters)
            except json.JSONDecodeError:
                parameters = {}
        if parameters is None:
            parameters = {}
        question = obj.get("clarification_question")
        if status not in {"MATCH", "CLARIFY", "NO_MATCH"}:
            raise ValueError(f"Invalid workflow routing status: {status}")
        if not isinstance(name, str) or not isinstance(confidence, (int, float)):
            raise ValueError("Router response must identify a workflow and numeric confidence.")
        if not isinstance(parameters, dict):
            raise ValueError("Router parameters must be a JSON object.")
        confidence = max(0.0, min(1.0, float(confidence)))
        name = name.strip().upper()
        if status == "CLARIFY":
            clarification_workflow = name if self.registry.get(name) else "CLARIFY"
            return WorkflowRequest(clarification_workflow, confidence, {}, status, str(question or "Could you clarify what you want me to do?"), source)
        if status == "NO_MATCH" or name == "NO_MATCH" or confidence < 0.45:
            return WorkflowRequest("NO_MATCH", confidence, {}, "NO_MATCH", None, source)

        spec = self.registry.get(name)
        if spec is None:
            return WorkflowRequest("NO_MATCH", confidence, {}, "NO_MATCH", None, source)
        if not parameters:
            parameters = {
                key: obj[key]
                for key in (*spec.required, *spec.optional)
                if key in obj
            }
        try:
            spec.validate_parameters(parameters)
            if spec.handler == "chain":
                self._validate_chain(parameters.get("steps"))
        except (TypeError, ValueError) as exc:
            return WorkflowRequest(
                "CLARIFY", confidence, {}, "CLARIFY",
                f"I need a little more detail before using {name}: {exc}", source,
            )
        return WorkflowRequest(name, confidence, parameters, "MATCH", None, source)

    def _validate_chain(self, steps: Any) -> None:
        if not isinstance(steps, list) or not 1 <= len(steps) <= 5:
            raise ValueError("a workflow chain needs 1 to 5 steps")
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict) or set(step) - {"workflow", "parameters"}:
                raise ValueError(f"step {index} has an invalid structure")
            name = str(step.get("workflow", "")).upper()
            spec = self.registry.get(name)
            if name in {"NO_MATCH", "WORKFLOW_CHAIN"} or not spec or not spec.chainable:
                raise ValueError(f"step {index} uses an unavailable workflow")
            spec.validate_parameters(step.get("parameters", {}))

    @staticmethod
    def _extract_object(raw: str) -> dict:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("Router returned no JSON object.")
            parsed = json.loads(cleaned[start:end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("Router response must be a JSON object.")
        return parsed


class GeminiCLIFallback:
    """One-shot analyzer; it cannot execute registered workflows or alter project files."""

    SYSTEM_PROMPT = """You are a fallback intent analyst for a local desktop agent. You do not execute actions and must not use tools, search, inspect files, edit files, or switch modes. Return one JSON object only with keys status, workflow, confidence, parameters, clarification_question. Select only an exact workflow name from the supplied allow-list. Use MATCH only when all required parameters are available. Use CLARIFY and ask one concise question when the user's intent is recognizable but a required value is missing. Use NO_MATCH when none of the registered workflows fits. Never invent tools or report execution."""

    def __init__(self, registry: WorkflowRegistry, *, enabled: bool = True, timeout: float = 45.0, command: str = "gemini", model: str = "flash"):
        self.registry = registry
        self.enabled = enabled
        self.timeout = max(5.0, float(timeout))
        self.command = command
        self.model = model

    async def resolve(self, message: str, primary: WorkflowRequest) -> WorkflowRequest:
        if not self.enabled:
            raise RuntimeError("Gemini CLI fallback is disabled.")
        import asyncio

        raw = await asyncio.to_thread(self._invoke, message, primary)
        from agent.workflows.router import WorkflowRouter

        result = WorkflowRouter(None, self.registry)._parse_response(raw, source="gemini_cli")
        if result.status == "MATCH":
            # Parse already checked allow-list and required parameter shape. Keep the fallback one-shot.
            return result
        return result

    def _invoke(self, message: str, primary: WorkflowRequest) -> str:
        import base64
        import os
        import shutil
        import subprocess
        import tempfile

        executable = shutil.which(self.command)
        if not executable:
            raise FileNotFoundError("Gemini CLI was not found on PATH. Install/authenticate it or disable Gemini fallback.")
        if os.name == "nt":
            ps1 = os.path.splitext(executable)[0] + ".ps1"
            if os.path.exists(ps1):
                executable = ps1
        workflow_list = self.registry.descriptions()
        prompt = (
            f"{self.SYSTEM_PROMPT}\n\nAllowed workflows and required parameters:\n{workflow_list}\n\n"
            f"User request:\n{message}\n\nPrimary router's result (source={primary.router_source}):\n"
            f"status={primary.status}; workflow={primary.workflow}; question={primary.clarification_question or ''}\n\n"
            "Do not call any tools. Return only the required JSON."
        )
        with tempfile.TemporaryDirectory(prefix="desktop_agent_gemini_") as isolated_cwd:
            policy_path = os.path.join(isolated_cwd, "deny-tools.toml")
            with open(policy_path, "w", encoding="utf-8") as policy_file:
                policy_file.write(
                    '[[rule]]\ntoolName = "*"\ndecision = "deny"\n'
                    'priority = 999\ndenyMessage = "Tools are disabled for workflow analysis."\n'
                )
            if os.name == "nt":
                # Invoke npm's gemini.cmd safely and deny all Gemini CLI tools for this one-shot analysis.
                executable_b64 = base64.b64encode(executable.encode("utf-8")).decode("ascii")
                prompt_b64 = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
                model_b64 = base64.b64encode(self.model.encode("utf-8")).decode("ascii")
                policy_b64 = base64.b64encode(policy_path.encode("utf-8")).decode("ascii")
                script = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$cli = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{executable_b64}'))
$prompt = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{prompt_b64}'))
$model = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{model_b64}'))
$policy = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{policy_b64}'))
$cliResult = & $cli --prompt $prompt --output-format json --approval-mode plan --model $model --admin-policy $policy --skip-trust
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {{ exit $exitCode }}
[Console]::Out.Write(($cliResult -join [Environment]::NewLine))
"""
                encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
                command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
            else:
                command = [executable, "--prompt", prompt, "--output-format", "json", "--approval-mode", "plan", "--model", self.model, "--admin-policy", policy_path, "--skip-trust"]
            completed = subprocess.run(
                command,
                cwd=isolated_cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        if completed.returncode != 0:
            error = (completed.stderr or completed.stdout or "Gemini CLI failed.").strip()
            raise RuntimeError(error[-1000:])
        stdout = completed.stdout.strip().lstrip("\ufeff")
        stderr = completed.stderr.strip()
        response = self._extract_cli_response(stdout) or self._extract_cli_response(stderr)
        if response:
            return response
        diagnostic = f"stdout={stdout[:500]!r}; stderr={stderr[:300]!r}"
        raise ValueError(f"Gemini CLI returned no usable response ({diagnostic}).")

    @staticmethod
    def _extract_cli_response(stdout: str) -> Optional[str]:
        """Accept Gemini JSON envelopes, raw router JSON, and plain JSON fenced in text."""
        import re

        if not stdout:
            return None
        clean = re.sub(r"\x1b\[[0-9;]*m", "", stdout).strip()
        candidates = [clean]
        candidates.extend(line.strip() for line in clean.splitlines() if line.strip())
        decoder = json.JSONDecoder()
        for index, char in enumerate(clean):
            if char == "{":
                try:
                    embedded, _end = decoder.raw_decode(clean[index:])
                except json.JSONDecodeError:
                    continue
                candidates.append(json.dumps(embedded, ensure_ascii=False))
        for candidate in reversed(candidates):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, str) and parsed.strip():
                return parsed.strip()
            if isinstance(parsed, dict):
                # Gemini can emit the model's router object directly.
                if "workflow" in parsed and "status" in parsed:
                    return json.dumps(parsed, ensure_ascii=False)
                for key in ("response", "text", "content", "result", "message"):
                    value = parsed.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
                    if isinstance(value, dict) and value:
                        return json.dumps(value, ensure_ascii=False)
                for key in ("response", "text", "content", "result", "message"):
                    value = parsed.get(key)
                    if isinstance(value, list):
                        texts = [str(item.get("text", "")) for item in value if isinstance(item, dict)]
                        if any(text.strip() for text in texts):
                            return "\n".join(texts).strip()
        # Some CLI versions may ignore --output-format=json; let the strict workflow parser inspect text.
        if "{" in clean and "}" in clean:
            return clean
        return None
