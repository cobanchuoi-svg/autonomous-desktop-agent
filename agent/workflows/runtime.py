"""Validate and execute selected workflows through existing local modules."""

import asyncio
import json
import re
from typing import Any, Dict, Optional
from urllib.parse import quote_plus

from agent.workflows.models import WorkflowRequest, WorkflowResult
from agent.workflows.registry import WorkflowRegistry
from agent.workflows.router import WorkflowRouter
from agent.workflows.router import GeminiCLIFallback
from agent.workflows.script_manager import ScriptManager
from agent.logger import logger


class WorkflowRuntime:
    def __init__(self, provider: Any, engine: Any, registry: Optional[WorkflowRegistry] = None, plugin_manager: Any = None, gemini_enabled: bool = True, gemini_timeout: float = 45.0, gemini_model: str = "flash"):
        self.registry = registry or WorkflowRegistry()
        self.gemini_fallback = GeminiCLIFallback(self.registry, enabled=gemini_enabled, timeout=gemini_timeout, model=gemini_model)
        self.router = WorkflowRouter(provider, self.registry, fallback=self.gemini_fallback)
        self.provider = provider
        self.engine = engine
        self.plugin_manager = plugin_manager
        self.script_manager = ScriptManager()
        self._pending_clarification: Optional[tuple[str, str]] = None
        self._response_language: Optional[str] = None
        self._pending_text_write: Optional[dict[str, Any]] = None
        self._pending_script_draft: Optional[dict[str, Any]] = None

    async def handle(self, message: str, on_chat_start: Any = None, on_chat_token: Any = None) -> tuple[WorkflowRequest, WorkflowResult]:
        # 1. Handle pending Python script execution approval
        if self._pending_script_draft is not None:
            cmd = re.sub(r"\s+", " ", message.strip().casefold())
            draft = self._pending_script_draft
            task_id = re.escape(draft["task_id"].casefold())
            # Restrict approval to explicit commands only: "/run" or "run" (optionally followed by task_id)
            if re.fullmatch(rf"(?:/run|run)(?:\s+{task_id})?", cmd):
                self._pending_script_draft = None
                exec_result = self.script_manager.execute_draft(draft["task_id"])
                req = WorkflowRequest("DYNAMIC_SCRIPT", 1.0, {"task_id": draft["task_id"]}, "MATCH", None, "user_approval")
                if exec_result["success"]:
                    msg = (
                        f"✅ **Thực thi thành công** script '{draft['title']}' ({exec_result['duration_seconds']}s):\n\n"
                        f"```\n{exec_result['output']}\n```"
                    )
                    return req, WorkflowResult("DYNAMIC_SCRIPT", True, msg, exec_result)
                else:
                    msg = (
                        f"❌ **Thực thi script '{draft['title']}' thất bại**:\n\n"
                        f"```\n{exec_result['output']}\n```"
                    )
                    return req, WorkflowResult("DYNAMIC_SCRIPT", False, msg, exec_result, error=exec_result.get("stderr"))

            # Restrict reject to explicit commands: "/reject" or "cancel" (optionally followed by task_id)
            if re.fullmatch(rf"(?:/reject|cancel)(?:\s+{task_id})?", cmd):
                self._pending_script_draft = None
                self.script_manager.delete_draft(draft["task_id"])
                req = WorkflowRequest("DYNAMIC_SCRIPT", 1.0, {"task_id": draft["task_id"]}, "MATCH", None, "user_cancel")
                return req, WorkflowResult("DYNAMIC_SCRIPT", True, f"Bản thảo script '{draft['task_id']}' đã được hủy bỏ an toàn. Không có code nào được chạy.")

            # Any other message while a draft is pending must re-show the pending prompt, not execute anything
            question = (
                f"Bản thảo script '{draft['task_id']}' đang chờ bạn duyệt.\n"
                f"👉 Gõ **'run'** hoặc **'/run'** để THỰC THI.\n"
                f"👉 Gõ **'cancel'** hoặc **'/reject'** để HỦY BỎ."
            )
            return WorkflowRequest("CLARIFY", 1.0, {}, "CLARIFY", question, "local_rule"), WorkflowResult("CLARIFY", True, question)
        if self._pending_text_write is not None:
            command = re.sub(r"\s+", " ", message.strip().casefold())
            if re.fullmatch(r"(?:type it|write it|approve|yes,? type(?: it)?|gõ đi|gõ vào|nhập đi|đồng ý|duyệt|ok,? gõ đi)", command):
                request = WorkflowRequest(
                    "WRITE_TEXT_TO_APP", 1.0,
                    {"target_app": self._pending_text_write["target_app"],
                     "instruction": self._pending_text_write["instruction"]},
                    "MATCH", None, "user_approval",
                )
                result = await self._commit_pending_text_write()
                return request, result
            if re.fullmatch(r"(?:cancel|discard|no|bỏ|hủy|huỷ|thôi)", command):
                draft = self._pending_text_write
                self._pending_text_write = None
                return WorkflowRequest(
                    "WRITE_TEXT_TO_APP", 1.0,
                    {"target_app": draft["target_app"], "instruction": draft["instruction"]},
                    "MATCH", None, "user_cancel",
                ), WorkflowResult("WRITE_TEXT_TO_APP", True, "Draft discarded; nothing was typed.")
            question = "A draft is waiting for review. Reply 'type it' or 'gõ vào' to enter it, or 'cancel'/'bỏ' to discard it."
            return WorkflowRequest("CLARIFY", 1.0, {}, "CLARIFY", question, "local_rule"), WorkflowResult("CLARIFY", True, question)

        original_message = message
        pending_goal = None
        if self._pending_clarification is not None:
            pending_goal, question = self._pending_clarification
            self._pending_clarification = None
            message = (
                f"Continue the user's earlier request. Original request: {pending_goal}\n"
                f"Clarification question asked: {question}\nUser's clarification: {message}"
            )
        request = await self.router.route(message)
        if request.status == "CLARIFY":
            question = request.clarification_question or "Could you clarify what you want me to do?"
            self._pending_clarification = (pending_goal or original_message, question)
            return request, WorkflowResult("CLARIFY", True, question, {"router_source": request.router_source}, request.fallback_error)
        if request.workflow == "NO_MATCH":
            # Attempt to draft a safe Python script or suggest prompt refinement
            dynamic_proposal = await self._propose_dynamic_solution(original_message)
            if dynamic_proposal is not None:
                return request, dynamic_proposal

            message = "I couldn't match that request to a registered workflow."
            return request, WorkflowResult("NO_MATCH", False, message, {"router_source": request.router_source}, request.fallback_error or "no_matching_workflow")
        result = await self.execute(request, on_chat_start=on_chat_start, on_chat_token=on_chat_token)
        return request, result

    async def execute(self, request: WorkflowRequest, on_chat_start: Any = None, on_chat_token: Any = None) -> WorkflowResult:
        spec = self.registry.get(request.workflow)
        if spec is None:
            raise ValueError(f"Workflow '{request.workflow}' is not registered.")
        spec.validate_parameters(request.parameters)
        name, params = spec.name, request.parameters
        if spec.handler == "chat":
            answer_parts = []
            requested_language = params.get("language")
            if requested_language:
                self._response_language = str(requested_language)
            if on_chat_start:
                on_chat_start()
            system_prompt = (
                "You are Desktop AI Agent, an intelligent and friendly desktop assistant for Windows. "
                "Respond naturally, warmly, and helpfully in Vietnamese (or the language the user speaks). "
                "You can help users control their PC, launch applications, search Google, read on-screen text with OCR, "
                "and automate workflows. Keep your answers clear, conversational, and direct."
            )
            if self._response_language:
                system_prompt += (
                    f" Always respond in {self._response_language}, including short acknowledgements, "
                    "unless the user explicitly requests a different language."
                )
            async for token in self.provider.generate_stream(
                str(params["message"]),
                system_prompt=system_prompt,
                json_mode=False,
            ):
                answer_parts.append(token)
                if on_chat_token:
                    on_chat_token(token)
            return WorkflowResult(name, True, "".join(answer_parts).strip())
        if spec.handler == "open_app":
            app_name = str(params["app_name"]).strip()
            if not app_name or len(app_name) > 100:
                raise ValueError("app_name must be between 1 and 100 characters.")
            success = await self.engine.run_goal(f"open {app_name}")
            execution = getattr(self.engine, "last_execution_result", None)
            evidence = {
                "success": bool(getattr(execution, "success", success)),
                "route": getattr(execution, "route", ""),
                "reason": getattr(execution, "reason", ""),
                "error": getattr(execution, "error", None),
            }
            return WorkflowResult(name, success, f"{app_name} {'launched successfully' if success else 'could not be launched'}.", {"execution": evidence}, None if success else getattr(execution, "error", None))
        if spec.handler == "web_search":
            query = str(params["query"]).strip()
            if not query or len(query) > 500:
                raise ValueError("query must be between 1 and 500 characters.")
            url = "https://www.google.com/search?q=" + quote_plus(query)
            if self.plugin_manager:
                data = await asyncio.to_thread(self.plugin_manager.execute_action, "browser_plugin", "open_url", url=url)
            else:
                import webbrowser
                data = await asyncio.to_thread(webbrowser.open, url)
            return WorkflowResult(name, bool(data), f"Opened a web search for: {query}", {"url": url, "result": data})
        if spec.handler == "generate_text":
            instruction = str(params["instruction"]).strip()
            context = str(params.get("context", ""))
            answer = await self.provider.generate(f"Instruction: {instruction}\n\nContext:\n{context}", system_prompt="Complete the user's writing request. Return only the requested text.", json_mode=False)
            return WorkflowResult(name, True, answer.strip())
        if spec.handler == "write_text_to_app":
            return await self._write_text_to_app(
                str(params["target_app"]).strip(),
                str(params["instruction"]).strip(),
                str(params.get("window_title") or "").strip() or None,
            )
        if spec.handler == "read_screen":
            frame = await asyncio.to_thread(self.engine.capture.capture_frame)
            data = await asyncio.to_thread(self.engine.ocr.extract_text, frame)
            text = str(data.get("full_text", "")).strip()
            return WorkflowResult(name, bool(text), text or "No visible text was detected.", {"ocr": data}, None if text else "no_text_detected")
        if spec.handler == "fsm_task":
            goal = str(params["goal"]).strip()
            if not goal or len(goal) > 2000:
                raise ValueError("goal must be between 1 and 2000 characters.")
            launch_target, follow_up = self._split_app_launch_follow_up(goal)
            if launch_target and follow_up:
                # Unknown app names deliberately use the existing Windows Search route
                # in AgentEngine, then the FSM handles the remaining desktop task.
                launched = await self.engine.run_goal(f"open {launch_target}")
                if not launched:
                    execution = getattr(self.engine, "last_execution_result", None)
                    error = getattr(execution, "error", None)
                    return WorkflowResult(
                        name, False, f"Could not open {launch_target} through Windows Search.",
                        {"stage": "application_launch", "execution": {
                            "route": getattr(execution, "route", ""),
                            "reason": getattr(execution, "reason", ""),
                            "error": error,
                        }}, error,
                    )
                goal = follow_up
            success = await self.engine.run_goal(goal)
            execution = getattr(self.engine, "last_execution_result", None)
            message = "The existing desktop workflow completed the task." if success else "The existing desktop workflow could not complete the task."
            return WorkflowResult(name, success, message, {"execution": {
                "route": getattr(execution, "route", "fsm"),
                "reason": getattr(execution, "reason", ""),
                "error": getattr(execution, "error", None),
            }}, None if success else getattr(execution, "error", None))
        if spec.handler == "chain":
            return await self._execute_chain(params["steps"])
        if spec.handler == "approved_chain":
            definition = self.registry.approved_definition(name)
            if not definition:
                raise ValueError(f"Approved workflow definition for '{name}' is missing.")
            return await self._execute_chain(definition["steps"], params)
        raise ValueError(f"Workflow '{name}' has no supported local handler.")

    async def _write_text_to_app(self, app_name: str, instruction: str, window_title: Optional[str]) -> WorkflowResult:
        """Generate prose once and enter it once; hold source code for user review."""
        if not app_name or len(app_name) > 100 or not instruction or len(instruction) > 2000:
            return WorkflowResult("WRITE_TEXT_TO_APP", False, "The target app or writing instruction is invalid.", error="invalid_target_or_instruction")
        if app_name == "__active_document__":
            active_target = await asyncio.to_thread(self._get_active_text_editor)
            if active_target is None:
                return WorkflowResult(
                    "WRITE_TEXT_TO_APP", False,
                    "I couldn't identify a supported text editor in the foreground. Focus the open document and try again; nothing was typed.",
                    {"stage": "foreground_target"}, "unsupported_or_missing_foreground_editor",
                )
            app_name, window_title = active_target
        app_key = re.sub(r"[^a-z0-9]+", " ", app_name.casefold()).strip()
        text_apps = (
            "wps", "word", "notepad", "writer", "google docs", "libreoffice", "notepad++",
            "vs code", "vscode", "visual studio code", "code editor",
        )
        if not any(name in app_key for name in text_apps):
            return WorkflowResult(
                "WRITE_TEXT_TO_APP", False,
                f"'{app_name}' is not in the approved text-editor targets for this workflow.",
                {"target_app": app_name}, "unsupported_text_target",
            )
        code_target = bool(re.search(r"\b(?:vs\s+code|vscode|visual\s+studio\s+code|code\s+editor)\b", app_name, re.IGNORECASE))
        code_request = code_target or bool(re.search(
            r"\b(?:code|script|program|function|class|python|javascript|typescript|java|c\+\+|sql)\b|mã\s+nguồn|lập\s+trình",
            instruction,
            re.IGNORECASE,
        ))
        if code_request:
            system_prompt = (
                "Generate only the requested source code. Never execute it, modify files, or claim it was tested. "
                "Make the code complete and syntactically coherent. Do not add markdown fences or explanatory prose."
            )
            prompt = f"Generate code for review before it is entered into {app_name}.\nInstruction: {instruction}"
        else:
            system_prompt = (
                "Write only the requested content, in the same language as the instruction. "
                "When asked for a descriptive paragraph, write 4 or 5 complete, natural sentences "
                "with concrete details about the requested subject. "
                "For other requests, follow the requested format and length. "
                "Fill in every detail with concrete wording. Never use ellipses, blank lines, dotted blanks, underscores, "
                "brackets, placeholders, templates, or unfinished sentences. Do not add an introduction, explanation, "
                "markdown fence, or claim that you typed anything."
            )
            prompt = (
                "Write the complete final text for the open document. Return finished sentences, not a fill-in template.\n"
                f"Instruction: {instruction}"
            )
        generated_parts: list[str] = []
        try:
            async for fragment in self.provider.generate_stream(
                prompt, system_prompt=system_prompt, json_mode=False,
            ):
                generated_parts.append(fragment)
        except Exception as exc:
            return WorkflowResult(
                "WRITE_TEXT_TO_APP", False, "Text generation failed; nothing was typed.",
                {"stage": "generation"}, str(exc),
            )
        text = "".join(generated_parts).strip()
        if not code_request:
            text = " ".join(text.split())
        validation_error = None
        if not text:
            validation_error = "empty_generation"
        elif not code_request and re.search(
            r"\.{3,}|(?:\.\s*){5,}|(?:…\s*)+|_{3,}|\[[^\]]+\]|<[^>]+>", text,
        ):
            validation_error = "placeholder_or_ellipsis_detected"

        if validation_error is not None:
            return WorkflowResult(
                "WRITE_TEXT_TO_APP", False,
                "The generated draft was empty or contained unfinished placeholders, so nothing was typed.",
                {"stage": "generation_validation", "characters_generated": len(text)},
                validation_error,
            )
        self._pending_text_write = {
            "target_app": app_name,
            "window_title": window_title,
            "instruction": instruction,
            "text": text,
        }
        if code_request:
            return WorkflowResult(
                "WRITE_TEXT_TO_APP", True,
                f"Code draft for {app_name} (not typed):\n\n{text}\n\nReview it, then reply 'type it' / 'gõ vào' to enter it, or 'cancel' / 'bỏ' to discard it.",
                {"target_app": app_name, "window_title": window_title, "characters_generated": len(text),
                 "awaiting_user_review": True},
            )
        return await self._commit_pending_text_write()

    @staticmethod
    def _get_active_text_editor() -> Optional[tuple[str, str]]:
        """Resolve only a known editor from the current foreground window title."""
        try:
            import pygetwindow

            active = pygetwindow.getActiveWindow()
            title = (active.title or "").strip() if active else ""
        except Exception:
            return None
        if not title:
            return None
        normalized = re.sub(r"[^a-z0-9+#]+", " ", title.casefold()).strip()
        known_editors = (
            ("wps", r"\bwps(?:\s+office)?\b|\bkingsoft\b"),
            ("word", r"\b(?:microsoft\s+)?word\b|\bwinword\b"),
            ("notepad++", r"\bnotepad\s*\+\+"),
            ("notepad", r"\bnotepad\b"),
            ("libreoffice", r"\blibreoffice\b|\bwriter\b"),
            ("vscode", r"\b(?:visual\s+studio\s+code|vscode)\b"),
            ("google docs", r"\bgoogle\s+docs\b"),
        )
        for app_name, pattern in known_editors:
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                return app_name, title
        return None

    async def _commit_pending_text_write(self) -> WorkflowResult:
        """Type a generated or user-approved draft into its verified target window once."""
        from agent.actions.base import ActionCommand, ActionType

        draft = self._pending_text_write
        if draft is None:
            return WorkflowResult("WRITE_TEXT_TO_APP", False, "There is no draft waiting for approval.", error="no_pending_draft")
        self._pending_text_write = None
        app_name = draft["target_app"]
        window_title = draft.get("window_title")
        ui = self.engine.context.ui_automation
        active = await asyncio.to_thread(ui.activate_app_window, app_name, window_title)
        if not active:
            launched = await self.engine.run_goal(f"open {app_name}")
            if not launched:
                execution = getattr(self.engine, "last_execution_result", None)
                error = getattr(execution, "error", None) or f"Could not open {app_name}."
                return WorkflowResult("WRITE_TEXT_TO_APP", False, error, {"stage": "launch"}, error)
            active = await asyncio.to_thread(ui.activate_app_window, app_name, window_title, 5.0)
        if not active:
            target = f"'{window_title}' in {app_name}" if window_title else app_name
            error = f"Could not focus {target}; draft was not typed."
            return WorkflowResult("WRITE_TEXT_TO_APP", False, error, {"stage": "focus"}, error)

        created_new_document = False
        if not window_title:
            new_document = ActionCommand(
                action_type=ActionType.HOTKEY,
                params={"keys": ["ctrl", "n"]},
                reason=f"Create a fresh document in {app_name} because no document was specified",
            )
            new_document_result = await asyncio.to_thread(self.engine.dispatcher.dispatch, new_document)
            if not new_document_result.success:
                error = new_document_result.error or f"Could not create a fresh document in {app_name}."
                return WorkflowResult("WRITE_TEXT_TO_APP", False, error, {"stage": "new_document"}, error)
            await asyncio.sleep(0.25)
            created_new_document = True
            if not await asyncio.to_thread(ui.is_app_window_foreground, app_name):
                error = f"Focus left {app_name} after creating the new document; draft was not typed."
                return WorkflowResult("WRITE_TEXT_TO_APP", False, error, {"stage": "focus_after_new_document"}, error)

        before_frame = await asyncio.to_thread(self.engine.capture.capture_frame)
        command = ActionCommand(
            action_type=ActionType.WRITE,
            params={"text": draft["text"], "interval": 0.1},
            reason=f"Enter reviewed draft into {app_name}",
        )
        result = await asyncio.to_thread(self.engine.dispatcher.dispatch, command)
        if not result.success:
            return WorkflowResult("WRITE_TEXT_TO_APP", False, result.error or "Text entry failed.", {"stage": "typing"}, result.error)
        after_frame = await asyncio.to_thread(self.engine.capture.capture_frame)
        verification = self.engine.verifier.verify_post_action(
            command=command, result=result, before_frame=before_frame, after_frame=after_frame,
        )
        active_after = await asyncio.to_thread(ui.is_app_window_foreground, app_name, window_title)
        # Keep the original lightweight check: Windows UI Automation often
        # cannot read the editable document surface even when typing succeeded.
        # Require a foreground target and a localized visible change instead.
        change_detected = verification.diff_score > 0.0001
        verified = bool(result.success and active_after and change_detected)
        verification_data = verification.model_dump()
        verification_data["foreground_confirmed_after_write"] = active_after
        verification_data["content_match"] = None
        verification_data["is_valid"] = verified
        verification_data["change_detected"] = change_detected
        verification_data["reason"] = (
            f"Target window remained foreground and visible screen change was detected (diff score: {verification.diff_score:.4f})."
            if verified else
            "The target window was not foreground or no visible screen change was detected."
        )
        return WorkflowResult(
            "WRITE_TEXT_TO_APP", verified,
            (f"Text entered into {app_name}:\n\n{draft['text']}\n\nVerification: {verification_data['reason']}" if verified
             else f"Text may have been typed into {app_name}, but the target window or visible change could not be verified."),
            {"target_app": app_name, "window_title": window_title,
             "created_new_document": created_new_document,
             "characters_typed": len(draft["text"]), "text": draft["text"],
             "verification": verification_data},
            None if verified else verification_data["reason"],
        )

    @staticmethod
    def _split_app_launch_follow_up(goal: str) -> tuple[Optional[str], Optional[str]]:
        """Split a compound app launch from its follow-up desktop task when explicit."""
        import re

        match = re.match(
            r"^\s*(?:please\s+)?(?:mở|open|launch|start)\s+(.+?)\s+"
            r"(?:vào|into|then|rồi|và|and|sau\s+đó|and\s+then)\s+(.+?)\s*[.!?]*\s*$",
            goal,
            flags=re.IGNORECASE,
        )
        if not match:
            return None, None
        app_name, follow_up = match.groups()
        app_name = re.sub(r"\s+(?:app|application|program)$", "", app_name, flags=re.IGNORECASE).strip()
        follow_up = follow_up.strip()
        if not app_name or len(app_name) > 80 or not follow_up:
            return None, None
        description = re.match(r"^(?:tả|miêu\s+tả|mô\s+tả)\s+(.+)$", follow_up, flags=re.IGNORECASE)
        if description:
            follow_up = f"Trong tài liệu đang mở, hãy viết một đoạn văn miêu tả {description.group(1)}."
        else:
            description = re.match(r"^(?:describe)\s+(.+)$", follow_up, flags=re.IGNORECASE)
            if description:
                follow_up = f"In the open document, write a descriptive paragraph about {description.group(1)}."
        if re.match(r"^(?:document\w*|docx|tài\s+liệu|văn\s+bản)\b", follow_up, flags=re.IGNORECASE):
            follow_up = "Mở " + follow_up
        return app_name, follow_up

    async def _execute_chain(self, steps: Any, parent: Optional[Dict[str, Any]] = None) -> WorkflowResult:
        if not isinstance(steps, list) or not 1 <= len(steps) <= 5:
            raise ValueError("A workflow chain must contain 1 to 5 steps.")
        results = []
        for index, item in enumerate(steps):
            if not isinstance(item, dict) or set(item) - {"workflow", "parameters"}:
                raise ValueError(f"Workflow chain step {index + 1} has an invalid shape.")
            name = str(item.get("workflow", "")).upper()
            if name in {"NO_MATCH", "WORKFLOW_CHAIN"}:
                raise ValueError("Chains cannot contain NO_MATCH or nested WORKFLOW_CHAIN.")
            step_params = item.get("parameters", {})
            if not isinstance(step_params, dict):
                raise ValueError(f"Workflow chain step {index + 1} parameters must be an object.")
            spec = self.registry.get(name)
            if not spec or not spec.chainable:
                raise ValueError(f"Workflow '{name}' is not allowed in a chain.")
            # Permit explicit references to prior output only; never evaluate code/templates.
            step_params = self._resolve_refs(step_params, results, parent or {})
            result = await self.execute(WorkflowRequest(name, 1.0, step_params))
            results.append({"workflow": name, "success": result.success, "message": result.message, "data": result.data})
            if not result.success:
                return WorkflowResult("WORKFLOW_CHAIN", False, f"Stopped at step {index + 1} ({name}): {result.message}", {"steps": results}, result.error)
        return WorkflowResult("WORKFLOW_CHAIN", True, "All workflow steps completed.", {"steps": results})

    @classmethod
    def _resolve_refs(cls, value: Any, results: list, parent: Dict[str, Any]) -> Any:
        if isinstance(value, str) and value.startswith("$step."):
            parts = value[1:].split(".")
            if len(parts) < 3 or not parts[1].isdigit():
                raise ValueError(f"Invalid workflow reference: {value}")
            index = int(parts[1]) - 1
            if index < 0 or index >= len(results):
                raise ValueError(f"Workflow reference points to unavailable step: {value}")
            current: Any = results[index]
            for part in parts[2:]:
                if not isinstance(current, dict) or part not in current:
                    raise ValueError(f"Workflow reference does not exist: {value}")
                current = current[part]
            return current
        if isinstance(value, str) and value.startswith("$input."):
            key = value.split(".", 1)[1]
            if key not in parent:
                raise ValueError(f"Workflow input reference does not exist: {value}")
            return parent[key]
        if isinstance(value, dict):
            return {k: cls._resolve_refs(v, results, parent) for k, v in value.items()}
        if isinstance(value, list):
            return [cls._resolve_refs(v, results, parent) for v in value]
        return value

    async def _propose_dynamic_solution(self, user_request: str) -> Optional[WorkflowResult]:
        """When no registered workflow fits, use LLM to draft a safe Python script or suggest prompt refinement."""
        system_prompt = (
            "You are an expert desktop automation assistant. "
            "The user asked for an action that did not match standard built-in workflows. "
            "If the task can be safely accomplished via a concise Python script using standard libraries "
            "(such as webbrowser, subprocess, os, json, urllib, datetime), provide that script. "
            "Never use destructive commands (format, rm c:\\, reg delete). "
            "Return ONLY a JSON object: "
            '{"type": "code"|"suggestion", "title": "Short title", "python_code": "...code...", "suggested_prompt": "...alternative query..."}'
        )
        prompt = f"User request: '{user_request}'\nGenerate solution in strict JSON now."
        try:
            raw = await self.provider.generate(prompt, system_prompt=system_prompt, json_mode=True)
            parsed = self.router._extract_object(raw)
            sol_type = parsed.get("type", "suggestion")
            code = parsed.get("python_code", "").strip()

            if sol_type == "code" and code:
                title = parsed.get("title", user_request[:50])
                draft = self.script_manager.create_draft(code=code, title=title)
                self._pending_script_draft = draft

                text = (
                    f"Tôi không tìm thấy workflow dựng sẵn cho task này, nhưng tôi đã soạn một bản thảo Python để thực hiện:\n\n"
                    f"📌 **Nhiệm vụ**: {draft['title']}\n"
                    f"🆔 **Task ID**: `{draft['task_id']}`\n\n"
                    f"```python\n{draft['code']}\n```\n\n"
                    f"🔒 **Cơ chế an toàn (Chưa chạy)**:\n"
                    f"👉 Gõ **'run'** hoặc **'/run'** để **DUYỆT và thực thi** script này.\n"
                    f"👉 Gõ **'cancel'** hoặc **'/reject'** để **HỦY BỎ**."
                )
                return WorkflowResult("PROPOSED_SCRIPT", True, text, draft)

            elif sol_type == "suggestion" and parsed.get("suggested_prompt"):
                sug = parsed.get("suggested_prompt")
                text = (
                    f"Tôi chưa tìm thấy workflow phù hợp cho yêu cầu: '{user_request}'.\n\n"
                    f"💡 **Gợi ý**: Bạn có thể thử diễn đạt lại như sau:\n"
                    f"👉 \"{sug}\""
                )
                return WorkflowResult("SUGGESTION", True, text, {"suggested_prompt": sug})
        except Exception as exc:
            logger.warning(f"[WorkflowRuntime] Dynamic solution proposal failed: {exc}")
            return None
        return None
