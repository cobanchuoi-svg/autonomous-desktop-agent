# Project State: Desktop AI Agent

**Generated**: 2026-10-27
**Target Platform**: Windows 11 / Windows 10
**Runtime Environment**: Python 3.12 / 3.11, Local Ollama (`qwen2.5:3b`), PaddleOCR 3.7.0 / PaddlePaddle 3.3.1

> This is a point-in-time local project snapshot, not a release checklist. Entries below describe the author's environment and should not be read as independently reproduced or guaranteed status.

---

## 1. System Overview & Status

The Desktop AI Agent is an autonomous, locally hosted desktop automation engine built with Clean Architecture, strict Dependency Injection, and a deterministic 11-State Finite State Machine (FSM). It eliminates unbounded while-loops in favor of verified perception, planning, action dispatching, and recovery.

### Subsystem Implementation Matrix
| Subsystem | Architecture / Implementation | Health / Status |
| :--- | :--- | :--- |
| **FSM Engine** | 11 discrete states (`IDLE`, `OBSERVE`, `RETRIEVE_MEMORY`, `THINK`, `VERIFY_ACTION`, `ACT`, `VERIFY_RESULT`, `REMEMBER`, `RECOVERY`, `ERROR`, `SHUTDOWN`) with SQLite state persistence | 100% Implemented & Passing |
| **Vision (Screen Capture)** | High-speed multi-monitor MSS capture with Pillow `ImageGrab` and fallback handling | Operational |
| **Vision (OCR Perception)** | Dual-format PaddleOCR processor supporting both PaddleOCR 2.x and PaddleOCR 3.x (PaddleX architecture) | Operational |
| **Process Isolation** | Multiprocessing-isolated OCR worker pool (`IsolatedOCRClient`) preventing main-loop GIL contention | Operational |
| **Brain / Reasoning** | Ollama Provider with `qwen2.5:3b`, deterministic JSON schema enforcement, multi-step task decomposition | Operational |
| **Action Execution** | Mouse (`pynput`), Keyboard (`pyautogui`), File I/O, OS Application Controller with Windows Registry discovery | Operational |
| **Safety Guard** | Static & runtime blocked keyword enforcement preventing dangerous shell and registry execution | Operational |
| **Memory System** | 3-tier memory (Ephemeral short-term, working goal/task memory, persistent SQLite WAL with Single-Writer FIFO queue) | Operational |
| **Action Verifier** | Pre/Post action ROI structural similarity checker, variance analysis, and Windows window state verification | Operational |

---

## 2. Directory Structure

```text
desktop-ai-agent/
├── agent/
│   ├── actions/               # Mouse, keyboard, application, file actions, and dispatcher
│   ├── brain/                 # Qwen client, task planner, recovery planner, teacher AI
│   ├── core/                  # Engine orchestration, container DI, exceptions, FSM states & machine
│   ├── llm/                   # Ollama, LlamaCpp, Transformers, and Mock providers
│   ├── memory/                # SQLite manager, WAL single-writer queue, memory retrieval & compression
│   ├── ui/                    # CustomTkinter live FSM dashboard
│   ├── verifier/              # ROI difference checker, state validator, action verifier
│   ├── vision/                # Screen capture, dual PaddleOCR pipeline, isolated subprocess worker
│   ├── config.py              # Pydantic v2 settings with JSON fallback
│   ├── logger.py              # Loguru structured logging with console/file sinks
│   └── main.py                # CLI and GUI entry point with startup diagnostics
├── tests/                     # Pytest suite covering actions, FSM, memory, plugins, vision
├── config.json                # Runtime configuration
├── pyproject.toml             # Project metadata & build tool configuration
└── requirements.txt           # Python dependency specifications
```
