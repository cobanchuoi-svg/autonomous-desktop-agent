"""OCR backend selection from configuration; expensive models stay lazy-loaded."""

def create_ocr_processor(engine: str = "hybrid"):
    name = (engine or "hybrid").strip().casefold()
    if name in {"hybrid", "auto", "default"}:
        from agent.vision.hybrid_ocr import HybridOCRProcessor
        return HybridOCRProcessor()
    if name in {"windows", "windows_ocr", "winrt", "native"}:
        from agent.vision.windows_ocr import WindowsMediaOCRProcessor
        return WindowsMediaOCRProcessor()
    if name in {"gemini", "gemini_vision", "vision"}:
        from agent.vision.gemini_ocr import GeminiVisionOCRProcessor
        return GeminiVisionOCRProcessor()
    if name in {"paddle", "paddleocr"}:
        from agent.vision.ocr import OCRProcessor
        return OCRProcessor()
    if name in {"florence", "florence2", "florence-2"}:
        from agent.vision.florence_ocr import Florence2OCRProcessor
        return Florence2OCRProcessor()
    raise ValueError(f"Unsupported OCR engine '{engine}'. Use 'hybrid', 'windows', 'gemini', 'paddleocr', or 'florence2'.")
