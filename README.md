# Desktop AI Agent

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-pytest-blue)](tests/)

An experimental Windows desktop agent built around a simple principle:

> **Route the request first. Use perception only when desktop context is actually needed.**

The project combines deterministic workflows, local Windows OCR, UI Automation, coordinate-aware elements, and an optional LLM router. Its document-focused path is designed for independent file observation and structural analysis; it is a learning/research project, not a replacement for a general-purpose commercial computer-use system.

## What it can do

- Route English and Vietnamese requests to registered workflows.
- Open supported applications and search the web.
- Read visible screen text using Windows Media OCR.
- Represent OCR/UI Automation output as text elements with screen coordinates.
- Distinguish elements belonging to the foreground window, a popup, or the desktop.
- Scan image files directly from memory with Pillow, without opening an image viewer.
- Analyze each document independently with local spatial rules and return `PASS`, `REVIEW_REQUIRED`, or `SCHEMA_DRIFT`.
- Keep a session-local reference to the latest successfully scanned document for explicit follow-up commands such as copying the selected image into WPS.
- Generate text and enter it into supported text editors.
- Use the existing FSM only for complex multi-step desktop tasks.
- Create draft scripts for unknown tasks, requiring explicit approval before execution.

## How it works

```text
User message
    │
    ▼
Workflow Router
    ├── OPEN_DOCUMENT_FOREGROUND
    ├── SCAN_DOCUMENT
    └── COPY_IMAGE_TO_WPS
                 │
                 ▼
          DocumentAgent
                 │
        ┌────────┴────────┐
        │                 │
   Image input       PDF input
   Pillow/RAM        open viewer + capture
        │                 │
        └────────┬────────┘
                 ▼
              OCR
       text + bounding boxes
                 │
                 ▼
       Brain structural analysis
   rows / columns / headers / geometry
                 │
                 ▼
      PASS / REVIEW_REQUIRED / SCHEMA_DRIFT
                 │
                 ▼
        DocumentAgentResult
```

`SCAN_DOCUMENT` is an analysis workflow and does not paste data. `COPY_IMAGE_TO_WPS` first analyzes the image, then copies the original image through the Windows clipboard; it is not an OCR-to-Excel exporter.

### Document Agent modules

| Layer | Files | Responsibility |
| --- | --- | --- |
| Coordinator | `agent/core/document_agent.py` | Coordinates ingestion, OCR, Brain analysis, and optional memory updates. |
| Ingestion/layout | `agent/actions/window_layout.py` | Validates files; image scans are headless, while PDF observation currently uses the foreground viewer path. |
| Capture/OCR | `agent/vision/capture.py`, `factory.py`, `windows_ocr.py`, `hybrid_ocr.py`, `ocr.py`, `parser.py`, `roi.py` | Produces OCR text, elements, confidence, and bounding boxes. |
| Brain geometry | `agent/brain/spatial_mapping.py` | Groups rows, classifies screen structure, and maps spatial boundaries. |
| Brain decision | `agent/brain/brain_client.py`, `structural_analysis.py` | Builds independent per-file contexts and emits deterministic decisions. |
| Workflow boundary | `agent/workflows/router.py`, `registry.py`, `runtime.py` | Routes document commands and preserves the latest successful document path for explicit follow-ups. |
| WPS action | `agent/actions/image_clipboard.py` | Copies the original image into WPS; it does not generate spreadsheet data. |

### Document Agent limitations

The current Document Agent ends at:

```text
PDF/Image → OCR → spatial/structural analysis → decision
```

The following are not implemented in this path yet:

- native multi-page PDF parsing/rendering;
- business-field extraction for invoices or airway bills;
- date, number, and currency normalization;
- field-level schema validation and audit export;
- Excel workbook generation;
- Word template filling or placeholder replacement.

For these capabilities, the intended extension is to add separate ingestion adapters, business extraction, normalization, validation, and exporters after the existing Brain layer rather than replacing the coordinator.

### Perception model

`Windows.Media.Ocr` is the default local OCR engine. It returns text and word bounding boxes without a GPU or a large model download.

Elements are tagged with a surface:

| Surface | Meaning |
| --- | --- |
| `foreground_window` | Belongs to the active application window. |
| `popup` | Belongs to the active dialog, menu, or popup window. |
| `desktop` | Screen-level content such as taskbar/background. |

The ROI helpers keep crop offsets. OCR can run on a window or popup crop while resulting coordinates still map back to the full desktop correctly.

```text
Full screenshot
    → choose active-window / popup region
    → crop ROI
    → OCR local coordinates
    → add crop offset
    → click-safe desktop coordinates
```

Gemini Vision is an optional fallback for cases where local text OCR cannot locate the requested element. It is not intended to run on every observation.

## Quick start

### 1. Install

```powershell
git clone https://github.com/cobanchuoi-svg/autonomous-desktop-agent.git
cd desktop-ai-agent

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Windows OCR uses Python/WinRT namespaces declared in `requirements.txt`. Your Windows installation must also have at least one OCR language pack installed.

### 2. Select an LLM

The project supports an optional cloud Gemini provider and local Ollama.

For local Ollama:

```powershell
ollama pull qwen2.5:3b
ollama serve
```

Then use a local override file named `config.local.json`:

```json
{
  "llm": {
    "provider": "ollama",
    "ollama_model": "qwen2.5:3b"
  }
}
```

For Gemini, put the API key in `config.local.json` or set `GEMINI_API_KEY`. Do not commit either option.

### 3. Start the chat UI

```powershell
python -m agent.main --gui
```

Example requests:

```text
Open Chrome
Search tin tức mới nhất
Read text on screen
Mở Notepad và viết một đoạn văn tả con mèo
```

## Safety model

- Registered workflows use an allow-list and validate required parameters.
- Coordinates come from the current `CoordinateRegistry` and screen hash; stale elements are rejected.
- Actions requiring approval are blocked by `ActionDispatcher` until a workflow obtains explicit user consent.
- Dynamic Python scripts are saved as drafts and only run after `run` / `/run` approval.
- Destructive command patterns are blocked by the safety guard.

## Learning without autonomous self-modification

The agent can learn from outcomes in a controlled way:

```text
Task → action result → memory / lesson → better future routing or proposal
```

For example, it can retain an action history, record a failure pattern, or draft a workflow/script for a task that is not yet supported. A draft is not active automatically: the user must review and explicitly approve it.

The agent does **not** silently edit Python source files, install dependencies, change configuration, commit code, or push to GitHub. Changes to the project follow a deliberate human-in-the-loop process:

```text
Agent proposes a change
    → user reviews and approves it
    → implementation is tested
    → user commits the verified change
```

This keeps learning useful without giving an experimental desktop agent unchecked control over the codebase or the machine.

## Development commands

```powershell
# Check configured capture, OCR, database, and LLM backends
python -m agent.main --check

# Run tests
python -m pytest tests
```

## Current limitations

- Windows OCR is fast for readable UI text, but does not understand icons or overall layout.
- OCR language quality depends on installed Windows OCR language packs and visible font size.
- PDF scanning currently opens the document in an external viewer and captures the visible screen; multi-page native PDF ingestion is not implemented.
- Structural analysis is deterministic and independent per file, but it does not by itself produce normalized business records or Excel/Word output.
- Copying an image into WPS is a GUI clipboard action and currently does not verify the exact post-paste content.
- Text-entry verification confirms foreground focus and visible screen change; it cannot always read the exact final editor content through Windows UI Automation.
- `Stop` is cooperative: it cannot instantly interrupt an already-running native OCR, PowerShell UIA probe, or keyboard injection.
- Gemini Vision adds latency, cost, and network dependency, so it remains an exceptional fallback.
- This project is experimental. Test only with non-sensitive windows and data.

## Next roadmap

- Native PDF ingestion with page-by-page rendering.
- Business-field extraction and normalization for one concrete document schema.
- Field-level validation with explicit review reasons and audit records.
- Excel export with correct number/date cell types.
- Word template filling only after the document schema and review flow are stable.
- ROI selection from foreground-window and popup bounds.
- Screen/ROI hashing and OCR cache for unchanged screens.
- Better popup classification and container-aware target selection.
- Quality-based vision fallback when local OCR is insufficient, not merely empty.
- Stronger text-entry verification where an application exposes accessible document text.
- Benchmarks for screenshot capture, OCR, UI Automation, routing, and action verification.

## License

Released under the [MIT License](LICENSE).
