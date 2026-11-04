# Desktop AI Agent

A Windows desktop AI agent with a local chat UI. It routes user requests to registered workflows (web search, app launch, text entry, and screen reading) and delegates multi-step desktop tasks to a finite-state machine (FSM). The project includes screen capture, OCR, UI Automation, keyboard and mouse actions, and SQLite-backed memory.

> **Status:** Experimental. This is a personal prototype, not a production-ready or safety-certified automation tool. OCR can be slow, application focus can vary by Windows app, and text entry/verification still need testing on different systems.

---

## LLM Options

The agent supports three LLM configurations:

### Option A: Cloud Gemini API (Recommended default)
- Uses Google's Gemini REST API (e.g. `gemini-2.0-flash`).
- Supply your API key via the `GEMINI_API_KEY` environment variable or in `config.local.json`.
- **Privacy Notice:** When using the Gemini option, your prompt messages, instructions, and OCR text extracted from the screen are transmitted to Google's API for processing.

### Option B: Local Ollama (Private & Offline)
- Uses a locally hosted model such as `qwen2.5:3b`.
- Run `ollama pull qwen2.5:3b` and start the Ollama service (`ollama serve`).
- Completely private: no screen data or queries leave your local machine.

### Option C: Gemini CLI (Advanced & Opt-in)
- Advanced option using a locally authenticated `gemini` CLI (`provider: "gemini_cli"`).
- **Warning on `--yolo`:** The CLI runs with the `--yolo` flag enabled, which allows the CLI to auto-approve its own tool calls without interactive confirmation prompts. Use with caution.

---

## Configuration & Precedence

Settings are loaded with the following precedence (highest first):

1. **Environment Variables:**
   - `AGENT_LLM__GEMINI_API_KEY`
   - `GEMINI_API_KEY`
   - `GOOGLE_API_KEY`
2. **`config.local.json`** (git-ignored):
   - Copy `config.local.example.json` to `config.local.json` and paste your key.
   - Any settings in `config.local.json` are deep-merged over `config.json`.
3. **`config.json`**:
   - Base committed repository configuration. Contains model defaults and safety limits. Never commit API keys to this file.

---

## What It Can Do

- Chat and answer queries using the configured LLM.
- Route requests to registered workflows:
  - Application launch via Windows Search / executable resolution.
  - Web search via default browser.
  - Text generation and writing to open documents (Notepad, Word, WPS, VS Code).
  - Screen reading using OCR (PaddleOCR).
- Propose dynamic Python scripts for unmatched workflows with strict user approval (`/run` or `run` to execute, `/reject` or `cancel` to discard).
- Multi-step task execution through the FSM state machine.
- Store goals, actions, and memory in SQLite.

---

## Requirements

- Windows 10 or 11, with an interactive logged-in desktop session.
- Python 3.11 or 3.12 recommended.
- Either:
  - A Google Gemini API key (Option A), OR
  - [Ollama](https://ollama.com/) running locally (Option B).
- PaddleOCR / PaddlePaddle installed if using the screen reading / OCR backend.

---

## Setup

From the project directory in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Configure Your LLM:

**Option A (Gemini API):**
```powershell
$env:GEMINI_API_KEY="your-api-key-here"
```
Or create `config.local.json`:
```json
{
  "llm": {
    "provider": "gemini",
    "gemini_api_key": "your-api-key-here"
  }
}
```

**Option B (Local Ollama):**
```powershell
ollama pull qwen2.5:3b
```
In `config.local.json` (or `config.json`):
```json
{
  "llm": {
    "provider": "ollama",
    "ollama_model": "qwen2.5:3b"
  }
}
```

---

## Run the Agent

Launch the CustomTkinter GUI dashboard:

```powershell
python -m agent.ui.launcher
```

Or run via the main CLI:

```powershell
python -m agent.main --gui
```

Keep the Windows desktop unlocked and visible while using desktop automation actions.

---

## Tests

Run the test suite with:

```powershell
python -m pytest tests
```

---

## Contributing & License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details. Replace the placeholder in `LICENSE` before publishing.
