# Desktop AI Agent

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-pytest-blue)](tests/)

An experimental Windows desktop agent built around a simple principle:

> **Route the request first. Use perception only when desktop context is actually needed.**

The project combines deterministic workflows, local Windows OCR, UI Automation, coordinate-aware elements, and an optional LLM router. It is a learning/research project, not a replacement for a general-purpose commercial computer-use system.

## What it can do

- Route English and Vietnamese requests to registered workflows.
- Open supported applications and search the web.
- Read visible screen text using Windows Media OCR.
- Represent OCR/UI Automation output as text elements with screen coordinates.
- Distinguish elements belonging to the foreground window, a popup, or the desktop.
- Generate text and enter it into supported text editors.
- Use the existing FSM only for complex multi-step desktop tasks.
- Create draft scripts for unknown tasks, requiring explicit approval before execution.

## How it works

```text
User message
    │
    ▼
Workflow Router ──► CHAT / OPEN_APP / WEB_SEARCH / WRITE_TEXT_TO_APP / READ_SCREEN
    │
    └──► FSM_TASK only when a task requires multi-step desktop interaction
                 │
                 ▼
        Screenshot → foreground window / popup surface → OCR + UI Automation
                 │
                 ▼
      UI elements: { text, bbox, surface, container_id, element_id }
                 │
                 ▼
          LLM selects an allowed element/action
                 │
                 ▼
      CoordinateRegistry resolves element_id → screen coordinate → action
```

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
git clone https://github.com/cobanchuoi-svg/myfistproject.git
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
- Text-entry verification confirms foreground focus and visible screen change; it cannot always read the exact final editor content through Windows UI Automation.
- `Stop` is cooperative: it cannot instantly interrupt an already-running native OCR, PowerShell UIA probe, or keyboard injection.
- Gemini Vision adds latency, cost, and network dependency, so it remains an exceptional fallback.
- This project is experimental. Test only with non-sensitive windows and data.

## Next roadmap

- ROI selection from foreground-window and popup bounds.
- Screen/ROI hashing and OCR cache for unchanged screens.
- Better popup classification and container-aware target selection.
- Quality-based vision fallback when local OCR is insufficient, not merely empty.
- Stronger text-entry verification where an application exposes accessible document text.
- Benchmarks for screenshot capture, OCR, UI Automation, routing, and action verification.

## License

Released under the [MIT License](LICENSE).
