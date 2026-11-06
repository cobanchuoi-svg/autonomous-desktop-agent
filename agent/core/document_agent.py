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


class DocumentEyes:
    """Perception layer: obtain the source image and run local OCR."""

    def __init__(self, capture: Any, ocr: Any):
        self.capture = capture
        self.ocr = ocr

    @staticmethod
    def _read_spreadsheet(path) -> dict:
        """Read .xlsx/.xls/.csv without OCR — return structured text dict."""
        ext = path.suffix.casefold()
        rows = []
        if ext == ".csv":
            import csv
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                rows = [row for row in reader if any(c.strip() for c in row)]
        else:
            try:
                import openpyxl
                wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
                ws = wb.active
                for row in ws.iter_rows(values_only=True):
                    cells = [str(c) if c is not None else "" for c in row]
                    if any(c.strip() for c in cells):
                        rows.append(cells)
                wb.close()
            except Exception:
                try:
                    import xlrd
                    wb = xlrd.open_workbook(str(path))
                    ws = wb.sheet_by_index(0)
                    for i in range(ws.nrows):
                        rows.append([str(ws.cell_value(i, j)) for j in range(ws.ncols)])
                except Exception as exc2:
                    return {"full_text": "", "elements": [], "error": str(exc2)}
        lines = ["\t".join(row) for row in rows]
        full_text = "\n".join(lines)
        return {"full_text": full_text, "elements": [], "rows": rows, "row_count": len(rows)}

    async def observe(self, document_path: str) -> tuple[Any, Dict[str, Any]]:
        path = Path(document_path)
        ext = path.suffix.casefold()
        if ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}:
            from PIL import Image

            frame = await asyncio.to_thread(Image.open, document_path)
            ocr_result = await asyncio.to_thread(self.ocr.extract_text, frame)
            return frame, ocr_result
        elif ext in {".xlsx", ".xls", ".csv"}:
            ocr_result = await asyncio.to_thread(self._read_spreadsheet, path)
            return None, ocr_result
        elif ext == ".pdf":
            try:
                import pypdfium2 as pdfium

                pdf = await asyncio.to_thread(pdfium.PdfDocument, str(path))
                frames = []
                full_texts = []
                all_elements = []
                for page in pdf:
                    pil_img = await asyncio.to_thread(lambda p=page: p.render(scale=2).to_pil())
                    frames.append(pil_img)
                    page_ocr = await asyncio.to_thread(self.ocr.extract_text, pil_img)
                    text = str(page_ocr.get("full_text", "")).strip()
                    if text:
                        full_texts.append(text)
                    all_elements.extend(page_ocr.get("elements", []))

                combined_ocr = {
                    "full_text": "\n\n".join(full_texts),
                    "elements": all_elements,
                    "pages": len(frames),
                }
                return (frames[0] if frames else None), combined_ocr
            except Exception as exc:
                logger.warning(f"[DocumentEyes] In-memory PDF render failed, falling back: {exc}")
                frame = await asyncio.to_thread(self.capture.capture_frame)
                ocr_result = await asyncio.to_thread(self.ocr.extract_text, frame)
                return frame, ocr_result
        else:
            frame = await asyncio.to_thread(self.capture.capture_frame)
            ocr_result = await asyncio.to_thread(self.ocr.extract_text, frame)
            return frame, ocr_result


class DocumentHands:
    """Action layer: prepare the observation surface without copying content."""

    def __init__(self, window_controller: Any):
        self.window_controller = window_controller

    async def prepare(self, document_path: str, *, wps_title: str) -> Any:
        return await asyncio.to_thread(
            self.window_controller.prepare_foreground_document,
            document_path,
            wps_title=wps_title,
        )


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
        eyes: Optional[DocumentEyes] = None,
        hands: Optional[DocumentHands] = None,
    ):
        self.capture = capture
        self.ocr = ocr
        self.brain = brain
        self.memory = memory
        if window_controller is None:
            from agent.actions.window_layout import DocumentWindowController

            window_controller = DocumentWindowController()
        self.window_controller = window_controller
        self.eyes = eyes or DocumentEyes(capture, ocr)
        self.hands = hands or DocumentHands(window_controller)

    async def scan(
        self,
        document_path: str,
        *,
        wps_title: str = "WPS",
        expected_headers: Optional[list[str]] = None,
    ) -> DocumentAgentResult:
        """Run layout -> Eyes -> OCR -> Brain -> Memory as one independent flow."""
        layout = await self.hands.prepare(document_path, wps_title=wps_title)
        if not layout.success:
            return DocumentAgentResult(False, layout.reason, error=layout.reason)

        try:
            if Path(document_path).suffix.casefold() not in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".pdf"}:
                await asyncio.sleep(0.8)
            _frame, ocr_result = await self.eyes.observe(document_path)
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


__all__ = [
    "DocumentAgent",
    "DocumentAgentResult",
    "DocumentEyes",
    "DocumentHands",
]
