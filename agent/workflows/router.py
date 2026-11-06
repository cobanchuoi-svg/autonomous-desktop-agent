"""LLM primary router and narrowly scoped Gemini CLI clarification fallback."""



import json

import re

from typing import Any, Optional



from agent.workflows.models import WorkflowRequest

from agent.workflows.registry import WorkflowRegistry





class WorkflowRouter:

    SYSTEM_PROMPT = """You are the primary intent router for a local desktop agent. Choose exactly one workflow from the supplied registry and extract only its parameters. Never invent workflows, tools, capabilities, or results. Do not execute anything. If essential information is missing, return status CLARIFY with one concise question. If no registered workflow can handle the request, return status NO_MATCH. Otherwise return status MATCH. Output one JSON object only: {\"status\":\"MATCH|CLARIFY|NO_MATCH\",\"workflow\":\"registered name or NO_MATCH\",\"confidence\":0.0,\"parameters\":{},\"clarification_question\":null}. Confidence is a rough routing estimate, not proof. Use FSM_TASK for complex desktop goals supported by the existing FSM. For multi-step requests use WORKFLOW_CHAIN with ordered steps [{\"workflow\":\"registered name\",\"parameters\":{...}}]. Never nest WORKFLOW_CHAIN. Do not choose a workflow until its required parameters are present.



Intent aliases: \"chép nội dung ảnh\", \"copy image content\", \"đưa ảnh sang sheet\", \"lấy ảnh vào WPS\", \"chèn ảnh vào bảng\", and \"paste the picture into WPS\" mean COPY_IMAGE_TO_WPS when an image path is present. \"Nội dung ảnh\" still means the image itself for this workflow; do not route it to text generation or OCR-only. If the user clearly asks to put an image into WPS but omits the path, return CLARIFY and ask only for the full image path."""



    def __init__(self, provider: Any, registry: WorkflowRegistry, fallback: Any = None):

        self.provider = provider

        self.registry = registry

        self.fallback = fallback

        self.last_document_path: Optional[str] = None



    @staticmethod

    def _clean_path(value: str) -> str:

        return value.strip().strip('"').replace(r"\_", "_")



    @classmethod

    def _extract_document_path(cls, text: str) -> Optional[str]:

        pattern = r'([A-Za-z]:[/\\][^<>|\r\n]+?\.(?:pdf|png|jpg|jpeg|bmp|tif|tiff|webp|xlsx|xls|csv))'

        match = re.search(pattern, text, flags=re.IGNORECASE)

        if not match:

            return None

        return cls._clean_path(match.group(1))

    async def route(self, message: str) -> WorkflowRequest:

        language_request = self._resolve_language_preference(message)

        if language_request is not None:

            return language_request



        # Fast path 1: Explicit app launch (e.g. "mở chrome", "open notepad") runs instantly in 0.001s locally

        local_app_route = self._resolve_explicit_app_launch(message)

        if local_app_route is not None:

            return local_app_route



        local_document_route = self._resolve_explicit_document_open(message)

        if local_document_route is not None:

            return local_document_route

        local_scan_route = self._resolve_explicit_document_scan(message)

        if local_scan_route is not None:

            return local_scan_route

        local_copy_route = self._resolve_explicit_image_copy(message)

        if local_copy_route is not None:

            return local_copy_route



        local_export_route = self._resolve_explicit_export_to_excel(message)
        if local_export_route is not None:
            return local_export_route

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



        image_alias_route = self._resolve_ai_image_copy_alias(message, primary)

        if image_alias_route is not None:

            return image_alias_route

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



    def _resolve_ai_image_copy_alias(

        self, message: str, primary: WorkflowRequest

    ) -> Optional[WorkflowRequest]:

        """Normalize AI-recognized image-to-WPS wording to one workflow."""

        text = re.sub(r"\s+", " ", message.strip())

        has_wps_target = bool(

            re.search(r"\b(?:wps|wps\s+office|sheet|spreadsheet|word|doc|docs|writer|notepad)\b", text, re.IGNORECASE)

        )

        has_copy_intent = bool(

            re.search(

                r"\b(?:chép|chep|copy|đưa|chèn|chen|paste|insert|put|lấy|lay|ghi|viết|viet|nhập|nhap)\b",

                text,

                re.IGNORECASE,

            )

        )

        has_image_reference = bool(

            re.search(

                r"\b(?:ảnh|anh|anhr|image|photo|picture|hình|hinh|chữ|chu|text|ocr|nội\s+dung\s+ảnh|image\s+content)\b",

                text,

                re.IGNORECASE,

            )

        )

        if not (has_wps_target and has_copy_intent and has_image_reference):

            return None



        path_match = re.search(

            r'"([^"]+\.(?:png|jpg|jpeg|bmp|tif|tiff|webp))"'

            r"|((?:[A-Za-z]:[\\/]|/)[^\"<>|]+?\.(?:png|jpg|jpeg|bmp|tif|tiff|webp))",

            text,

            re.IGNORECASE,

        )

        image_path = next(

            (group for group in (path_match.groups() if path_match else ()) if group),

            None,

        )

        if image_path:

            copy_content = bool(

                re.search(r"\b(?:nội\s+dung|content|chữ|chu|text|văn\s+bản|ocr|đọc)\b", text, re.IGNORECASE)

            )

            return WorkflowRequest(

                "COPY_IMAGE_CONTENT_TO_WPS" if copy_content else "COPY_IMAGE_TO_WPS",

                max(0.90, primary.confidence),

                {"image_path": self._clean_path(image_path), "wps_title": "WPS"},

                "MATCH",

                None,

                "llm_alias_normalizer",

            )

        return WorkflowRequest(

            "CLARIFY",

            max(0.90, primary.confidence),

            {},

            "CLARIFY",

            "Bạn gửi giúp mình đường dẫn đầy đủ của ảnh để mình chép vào WPS.",

            "llm_alias_normalizer",

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



    def _resolve_explicit_document_open(self, message: str) -> Optional[WorkflowRequest]:

        """Recognize local PDF/image foreground requests without an LLM call."""

        text = re.sub(r"\s+", " ", message.strip())

        match = re.match(

            r"^(?:please\s+)?(?:mở|open|show|hiện)\s+"

            r"(?:file\s+)?(.+?\.(?:pdf|png|jpg|jpeg|bmp|tif|tiff|webp|xlsx|xls|csv))"

            r"(?:\s+(?:lên|ra)\s+(?:toàn\s+màn\s+hình|full\s*screen|foreground))?"

            r"(?:\s+(?:và|and)\s+(?:để|keep)\s+(?:wps|wps office)\s+(?:chạy\s+)?(?:nền|background))?"

            r"\s*[.!?]*$",

            text,

            flags=re.IGNORECASE,

        )

        if not match:

            return None

        path = match.group(1).strip().strip('"')

        path = self._clean_path(path)

        return WorkflowRequest(

            "OPEN_DOCUMENT_FOREGROUND",

            0.99,

            {"document_path": path, "wps_title": "WPS"},

            "MATCH",

            None,

            "local_rule",

        )



    def _resolve_explicit_document_scan(self, message: str) -> Optional[WorkflowRequest]:

        """Recognize scan/analyze requests and route them to OCR + Brain."""

        text = re.sub(r"\s+", " ", message.strip())

        match = re.match(

            r"^(?:please\s+)?(?:quét|scan|ocr|đọc|phân\s+tích|analyze|analyse)\s+"

            r'(?:file\s+)?([^<>\r\n]+?\.(?:pdf|png|jpg|jpeg|bmp|tif|tiff|webp|xlsx|xls|csv))'

            r"(?:\s+(?:và|and)\s+(?:để|keep)\s+(?:wps|wps office)\s+(?:chạy\s+)?(?:nền|background))?"

            r"\s*[.!?]*$",

            text,

            flags=re.IGNORECASE,

        )

        if not match:

            path = self._extract_document_path(text)

            if not path or not re.match(r"^(?:quét|scan|ocr|đọc|phân\s+tích|analyze|analyse)\b", text, re.IGNORECASE):

                return None

            return WorkflowRequest(

                "SCAN_DOCUMENT", 0.99,

                {"document_path": path, "wps_title": "WPS"},

                "MATCH", None, "local_rule",

            )

        return WorkflowRequest(

            "SCAN_DOCUMENT",

            0.99,

            {"document_path": self._clean_path(match.group(1)), "wps_title": "WPS"},

            "MATCH",

            None,

            "local_rule",

        )



    def _resolve_explicit_image_copy(self, message: str) -> Optional[WorkflowRequest]:

        """Recognize image-path requests that should be copied into WPS."""

        text = re.sub(r"\s+", " ", message.strip())

        match = re.match(

            r"^(?:please\s+)?(?:chép|chep|copy|đưa|chèn|chen|lấy|lay|ghi|viết|viet|nhập|nhap)\s+"

            r"(?:(?:nội\s+dung|content|chữ|chu|text|văn\s+bản|file)\s+)?"

            r"(?:từ|tu|trong|from)?\s*"

            r"(?:anhr|ảnh|anh|image|photo|tài\s+liệu|file\s+(?:anhr|ảnh|anh))?\s*"

            r'"?([^"<>|\r\n]+?\.(?:png|jpg|jpeg|bmp|tif|tiff|webp|pdf))"?\s+'

            r"(?:vào|to|into)\s+(?:wps|wps\s+office|word|notepad)(?:\s+(?:sheet|spreadsheet|doc|docs|writer|document))?"

            r"\s*[.!?]*$",

            text,

            flags=re.IGNORECASE,

        )

        if match:

            copy_content = bool(

                re.search(r"\b(?:nội\s+dung|content|chữ|chu|text|ocr)\b", text, re.IGNORECASE)

            )

            return WorkflowRequest(

                "COPY_IMAGE_CONTENT_TO_WPS" if copy_content else "COPY_IMAGE_TO_WPS",

                0.99,

                {"image_path": self._clean_path(match.group(1)), "wps_title": "WPS"},

                "MATCH",

                None,

                "local_rule",

            )



        from_image_match = re.match(

            r"^(?:please\s+)?(?:chép|chep|copy|đưa|lấy|lay)\s+"

            r"(?:chữ|chu|text|nội\s+dung|content)\s+"

            r"(?:từ|tu|trong|from|from\s+the)\s+"

            r"(?:ảnh|anh|anhr|image|photo|hình|hinh)\s+"

            r'"?(.+?\.(?:png|jpg|jpeg|bmp|tif|tiff|webp))"?\s+'

            r"(?:vào|sang|to|into)\s+(?:wps|wps\s+office|word|notepad)(?:\s+(?:sheet|spreadsheet|doc|docs|writer|document))?"

            r"\s*[.!?]*$",

            text,

            flags=re.IGNORECASE,

        )

        if from_image_match:

            return WorkflowRequest(

                "COPY_IMAGE_CONTENT_TO_WPS",

                0.99,

                {"image_path": self._clean_path(from_image_match.group(1)), "wps_title": "WPS"},

                "MATCH",

                None,

                "local_rule",

            )



        intent = re.match(

            r"^(?:please\s+)?(?:chép|chep|copy|đưa|chèn|chen|gõ|paste|dán|ghi|viết|viet|nhập|nhap)\s+"

            r"(?:(?:nội\s+dung|content|chữ|chu|text|văn\s+bản|bảng|dữ\s+liệu)\s+)?"

            r"(?:anhr|ảnh|anh|image|photo|file|tài\s+liệu)?\s*"

            r"(?:đã\s+chọn|vừa\s+quét|này)?\s*"

            r"(?:vào|to|into|sang)\s+(?:wps|wps\s+office|word|notepad|doc|docs|writer|sheet|spreadsheet|excel|bảng\s+tính)(?:\s+(?:sheet|spreadsheet|doc|docs|writer|document|excel|bảng\s+tính))?"

            r"(?:\s+(?:được không|đc không|đc k|được chứ))?"

            r"\s*[.!?]*$",

            text,

            flags=re.IGNORECASE,

        )

        if intent:

            if getattr(self, "last_document_path", None):

                target_wps = "WPS"

                if re.search(r"\b(?:sheet|spreadsheet|excel|bảng\s+tính)\b", text, re.IGNORECASE):

                    target_wps = "WPS Sheet"

                return WorkflowRequest(

                    "COPY_IMAGE_CONTENT_TO_WPS",

                    0.99,

                    {"image_path": self.last_document_path, "wps_title": target_wps},

                    "MATCH",

                    None,

                    "session_memory",

                )

            return WorkflowRequest(

                "CLARIFY",

                0.98,

                {},

                "CLARIFY",

                "Bạn gửi giúp mình đường dẫn của ảnh/tài liệu hoặc bấm nút 'Chọn file' trên giao diện nhé.",

                "local_rule",

            )

        return None



    def _resolve_explicit_export_to_excel(self, message: str) -> Optional[WorkflowRequest]:
        """Recognize export-to-excel requests."""
        text = re.sub(r"\s+", " ", message.strip())
        # Match explicit path
        path_match = re.match(
            r"^(?:please\s+)?(?:xuất|xuat|export|chuyển|chuyen|convert|lưu|luu|tạo|tao|save)\s+"
            r"(?:(?:ảnh|anh|image|file|dữ\s+liệu|du\s+lieu|data|nội\s+dung|noi\s+dung)\s+)?"
            r"(?:ra|to|into|thành|thanh|as)?\s*"
            r"(?:file\s+)?(?:excel|xlsx|csv|spreadsheet|bảng\s+tính)\s*",
            text, flags=re.IGNORECASE,
        )
        # Follow-up: "xuất ra excel" with no path → use last_document_path
        followup = re.match(
            r"^(?:xuất|xuat|export|chuyển|chuyen|save|lưu|luu)\s+"
            r"(?:ra|to|as|thành|thanh)?\s*(?:file\s+)?(?:excel|xlsx|csv|bảng\s+tính|spreadsheet)"
            r"(?:\s+(?:được không|đc k|dc k))?\s*[.!?]*$",
            text, flags=re.IGNORECASE,
        )
        image_path = None
        if path_match:
            image_path = self._extract_document_path(text)
        if not image_path and (path_match or followup):
            image_path = getattr(self, "last_document_path", None)
        if not image_path:
            if path_match or followup:
                return WorkflowRequest(
                    "CLARIFY", 0.98, {}, "CLARIFY",
                    "Ban gui minh duong dan file anh hoac chon file truoc nhe.",
                    "local_rule",
                )
            return None
        return WorkflowRequest(
            "EXPORT_OCR_TO_EXCEL", 0.99,
            {"image_path": image_path},
            "MATCH", None, "local_rule",
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

