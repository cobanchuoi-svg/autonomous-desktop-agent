# Desktop AI Agent 🤖

[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform: Windows 10/11](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6.svg)](https://microsoft.com)
[![Tests Passing](https://img.shields.io/badge/tests-21%2F21%20passing-brightgreen.svg)](tests/)
[![OCR: Native WinRT (16ms)](https://img.shields.io/badge/OCR-Windows%20Native%2016ms-orange.svg)](agent/vision/windows_ocr.py)

An autonomous Windows Desktop AI Agent featuring a responsive Chat Dashboard, **16ms Ultra-Fast Native OCR**, **Hybrid Gemini Multimodal Vision**, deterministic **Finite State Machine (FSM)** action execution, and **Human-in-the-Loop Safety Sandboxing**.

---

## 🌟 Key Highlights

- ⚡ **Zero-GPU Ultra-Fast Native OCR (16-25ms)**: Uses `Windows.Media.Ocr` (WinRT). Replaced heavy PaddleOCR, achieving a **10,000x speedup** on standard CPU with zero heavy AI model downloads.
- 👁️ **Hybrid Multimodal Vision Fallback**: Automatically invokes Gemini 2.0 / 3.8 Flash Multimodal Vision when UI elements are complex, artistic, or unreadable by local OCR.
- 🧠 **Deterministic FSM Architecture**: Replaces fragile `while-true` loops with an auditable Finite State Machine (`OBSERVE` ➔ `PLAN` ➔ `ACT` ➔ `VERIFY` ➔ `RECOVER`).
- 🛡️ **Human-in-the-Loop Safety Sandbox**: Complex or dynamic scripts are presented as interactive drafts; user must explicitly confirm (`run` / `approve`) before any code executes.
- 💬 **Bilingual Natural Interaction**: Native support for English and Vietnamese conversational commands and desktop workflows.

---

## 🚀 Quickstart (30 Seconds)

### 1. Clone & Install
```powershell
git clone https://github.com/your-username/desktop-ai-agent.git
cd desktop-ai-agent

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install lightweight dependencies
pip install -r requirements.txt
```

### 2. Configure Your LLM
Create `config.local.json` (automatically protected by `.gitignore`):
```json
{
  "llm": {
    "provider": "gemini",
    "model_name": "gemini-3.8-flash",
    "gemini_api_key": "YOUR_GEMINI_API_KEY"
  }
}
```

> **💡 Model Selection Note:** Google AI Studio regularly rolls out newer model versions (e.g., `gemini-3.8-flash`, `gemini-flash-latest`, `gemini-2.5-pro`). You can freely change `"model_name"` in your `config.local.json` to whichever model is active in your region/account. The agent also includes built-in auto-recovery to gracefully migrate if an older model is deprecated.
>
> *(Or use 100% offline private local models via [Ollama](https://ollama.com/) with `ollama pull qwen2.5:3b`)*.

### 3. Launch GUI Dashboard
```powershell
python -m agent.main --gui
```

---

## 🏗️ Architecture

```
User Voice / Text Request
          │
          ▼
   [Workflow Router] ◄────► [Gemini 3.8 Flash / Ollama]
          │
    ┌─────┴────────────────────────┐
    ▼                              ▼
(Fast Path Workflows)       (Complex Multi-Step FSM)
- Open Applications         - OBSERVE (Native WinRT OCR 16ms)
- Web Search (Google)       - FALLBACK (Gemini Multimodal Vision)
- Text Injection to Windows - PLAN (Action Sequence)
- Screen Reading            - ACT (Win32 / PyAutoGUI mouse & keys)
                            - VERIFY (Visual & Process state checks)
```

---

## 🧪 Testing

Run the full automated test suite:
```powershell
python -m pytest tests
```
*All 21 unit tests cover configuration precedence, actions, FSM transitions, Windows Native OCR, and Hybrid Vision fallback.*

---

## 💖 Support & Sponsorship

This project is an independent open-source research initiative on **Embodied Desktop AI Agents & Hierarchical Action Policies**. If you find this project useful or would like to support ongoing development, please consider sponsoring:

- ⭐ **Star this repository** on GitHub!
- ☕ **Buy Me a Coffee**: [buymeacoffee.com/yourname](https://buymeacoffee.com)
- 💳 **PayPal**: [paypal.me/yourname](https://paypal.me)
- 🏦 **Vietnam Banking / Momo**: *(Update your payment details here)*
- 🤝 **Corporate Sponsorship / Research Collaboration**: Open for Master's/PhD lab collaboration and grants.

---

## 📄 License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for more information.
