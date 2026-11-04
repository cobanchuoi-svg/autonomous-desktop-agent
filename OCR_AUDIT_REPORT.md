# Optical Character Recognition (OCR) Audit & Compatibility Report

**Date of Audit**: 2026-10-27
**Target Architecture**: PaddleOCR 3.7.0 / PaddlePaddle 3.3.1 (Python 3.12) & PaddleOCR 2.x Backwards Compatibility

---

## 1. Executive Summary

A critical vision audit was performed on `agent/vision/ocr.py` and `agent/vision/ocr_worker.py` addressing two major historical issues:
1. **Synthetic Fallback Injections**: Removal of synthetic/fabricated UI text (`File`, `Edit`, `Terminal`, `Chrome`, `Visual Studio Code`).
2. **`ValueError: Unknown argument: use_gpu`**: Constructor signature mismatch between legacy PaddleOCR 2.x and PaddleOCR 3.x (PaddleX architecture).

Both issues have been resolved. The vision subsystem now runs real OCR extraction against desktop screen frames, extracts dynamic UI element coordinates, and rejects execution with `OCRUnavailableError` if the OCR engine is not installed.

---

## 2. Root Cause Analysis

### Issue A: Synthetic Fallback Injection
- **Root Cause**: `OCRProcessor.extract_text` previously contained a fallback block injecting 5 hardcoded UI elements when `PaddleOCR` was not available.
- **Impact**: The LLM observed synthetic text ("Chrome", "Visual Studio Code") on every frame, falsely concluding that applications were already open or present on screen.
- **Resolution**: Removed all synthetic lists. If PaddleOCR is missing, `OCRProcessor` raises `OCRUnavailableError` and fails the `OBSERVE` state directly to `ERROR`.

### Issue B: `use_gpu` Signature Crash
- **Root Cause**: In PaddleOCR 3.x (`paddlex` wrapper architecture):
  - `use_gpu` argument was replaced by `device="gpu"` or `device="cpu"`.
  - `use_angle_cls` was deprecated in favor of `use_textline_orientation`.
  - Passing `use_gpu` threw `ValueError: Unknown argument: use_gpu`.
  - On Windows with PaddlePaddle 3.3.1 CPU inference, OneDNN (`enable_mkldnn=True`) triggered `NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]`.
- **Resolution**:
  - Implemented dynamic constructor parameter detection in `create_paddle_engine()`.
  - Configured `use_doc_orientation_classify=False` and `use_doc_unwarping=False` (desktop screenshots do not require document unwarping).
  - Explicitly configured `enable_mkldnn=False` for CPU execution on Windows.
  - Implemented `parse_ocr_results()` to normalize both PaddleOCR 3.x dictionary output (`rec_texts`, `rec_scores`, `rec_polys`) and PaddleOCR 2.x nested line list output (`[[box, (text, conf)], ...]`).

---

## 3. Verification & Validation Evidence

### Test Execution: `tests/test_vision.py`
```text
tests/test_vision.py::test_screen_capture_and_dimensions PASSED          [ 14%]
tests/test_vision.py::test_ui_element_bounding_box_center PASSED         [ 28%]
tests/test_vision.py::test_find_elements_by_text PASSED                  [ 42%]
tests/test_vision.py::test_ocr_processor_clean_text PASSED               [ 57%]
tests/test_vision.py::test_ocr_raises_when_unavailable_and_never_fabricates PASSED [ 71%]
tests/test_vision.py::test_ocr_diagnostics_and_versions PASSED           [ 85%]
tests/test_vision.py::test_ocr_processes_real_screenshot PASSED          [100%]
======================= 7 passed in 31.63s =======================
```

### Health Check Output:
- **MSS Screen Capture**: AVAILABLE (1 physical monitor detected)
- **PaddleOCR Version**: 3.7.0
- **PaddlePaddle Version**: 3.3.1
- **OCR API Generation**: v3 (PaddleX)
- **Backend Operational Status**: OPERATIONAL
