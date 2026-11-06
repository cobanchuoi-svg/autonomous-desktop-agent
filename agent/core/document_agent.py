"""Unified document agent coordinating Eyes, OCR, Brain, Memory and window layout."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from agent.brain.brain_client import BrainClient
from agent.brain.structural_analysis import StructuralAnalysisResult
from agent.logger import logger


@dataclass
class DocumentAgentResult:
    success: bool
    message: str
    analysis: Optional[StructuralAnalysisResult] = None
    ocr: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class DocumentAgent:
    """Single orchestration boundary for the document-analysis tree."""

    def __init__(
        self,
        *,
        capture: Any,
        ocr: Any,
        brain: BrainClient,
        memory: Any = None,
        window_controller: Any = None,
    ):
        self.capture = capture
        self.ocr = ocr
        self.brain = brain
        self.memory = memory
        if window_controller is None:
            from agent.actions.window_layout import DocumentWindowController

            window_controller = DocumentWindowController()
        self.window_controller = window_controller

    async def scan(
        self,
        document_path: str,
        *,
        wps_title: str = "WPS",
        expected_headers: Optional[list[str]] = None,
    ) -> DocumentAgentResult:
        """Run layout -> Eyes -> OCR -> Brain -> Memory as one independent flow."""
        layout = await asyncio.to_thread(
            self.window_controller.prepare_foreground_document,
            document_path,
            wps_title=wps_title,
        )
        if not layout.success:
            return DocumentAgentResult(False, layout.reason, error=layout.reason)

        try:
            is_image = Path(document_path).suffix.casefold() in {
                ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"
            }
            if is_image:
                from PIL import Image

                frame = await asyncio.to_thread(Image.open, document_path)
                frame.load()
            else:
                await asyncio.sleep(0.8)
                frame = await asyncio.to_thread(self.capture.capture_frame)
            ocr_result = await asyncio.to_thread(self.ocr.extract_text, frame)
            analysis = await asyncio.to_thread(
                self.brain.analyze_ocr_result,
                ocr_result,
                file_id=document_path,
                expected_headers=expected_headers,
            )
            text = str(ocr_result.get("full_text", "")).strip()
            if self.memory is not None:
                self.memory.update_short_term(screen_text=text, success=analysis.status.value == "PASS")
                self.memory.add_memory_entry(
                    f"Document scan {document_path}: {analysis.status.value}/{analysis.screen_type.value}",
                    category="document_analysis",
                    importance=0.4,
                )
            header_names = ", ".join(header.name for header in analysis.headers) or "none detected"
            message = (
                f"Đã quét {document_path}.\n"
                f"Decision: {analysis.status.value}\n"
                f"Screen type: {analysis.screen_type.value}\n"
                f"Headers: {header_names}\n"
                f"AI required: {'yes' if analysis.ai_required else 'no'}"
            )
            if analysis.review_reason:
                message += f"\nReview reason: {analysis.review_reason}"
            return DocumentAgentResult(bool(text or analysis.headers), message, analysis, ocr_result)
        except Exception as exc:
            logger.exception(f"[DocumentAgent] Scan failed for {document_path}: {exc}")
            return DocumentAgentResult(False, f"Document scan failed: {exc}", error=str(exc))


__all__ = ["DocumentAgent", "DocumentAgentResult"]
