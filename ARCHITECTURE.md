# Architecture Specification: Desktop AI Agent

## 1. Architectural Philosophy: Clean Architecture & Perceptual Ports

The system adheres strictly to Clean Architecture separation of concerns:
- **Core Domain & Entities**: Domain models for actions (`ActionCommand`, `ActionResult`), goals, tasks, memory entries, lessons.
- **Perceptual Ports & Adapters**: Abstract interfaces (`BaseScreenCapture`, `BaseOCRProcessor`, `BaseLLMProvider`, `BaseDatabase`) decouple concrete dependencies (e.g. MSS, PaddleOCR, Ollama, SQLite).
- **Dependency Injection**: `agent/core/container.py` wires concrete singletons into `AgentEngine`.

---

## 2. Finite State Machine (FSM) Lifecycle

The autonomous cycle is driven by `StateMachine` (`agent/core/fsm/machine.py`) without unbounded while-true loops:

```
  +--------+
  |  IDLE  +<----------------------------------------------------+
  +---+----+                                                     |
      | (Goal Received)                                          |
      v                                                          |
  +---+----+                                                     |
  |OBSERVE +<----------------------------------------------+     |
  +---+----+                                               |     |
      | (Capture & OCR parsed)                             |     |
      v                                                    |     |
+-----+-----------+                                        |     |
| RETRIEVE_MEMORY |                                        |     |
+-----+-----------+                                        |     |
      | (Ranked short/long term contexts)                  |     |
      v                                                    |     |
  +---+----+                                               |     |
  | THINK  |                                               |     |
  +---+----+                                               |     |
      | (Action synthesised)                               |     |
      v                                                    |     |
+-----+---------+                                          |     |
| VERIFY_ACTION |                                          |     |
+-----+---------+                                          |     |
      | (Safety pass & ROI valid)                          |     |
      v                                                    |     |
  +---+----+                                               |     |
  |  ACT   |                                               |     |
  +---+----+                                               |     |
      | (Dispatched)                                       |     |
      v                                                    |     |
+-----+---------+                                          |     |
| VERIFY_RESULT |                                          |     |
+-----+---------+                                          |     |
      | (Action outcome verified)                          |     |
      v                                                    |     |
  +---+----+                                               |     |
  |REMEMBER|                                               |     |
  +---+----+                                               |     |
      |                                                    |     |
      +----[Goal Done]-------------------------------------+-----+
      |
      +----[Step Incomplete]-------------------------------+
```

### Failure Handling & Recovery Loop:
When action verification or perceptual validation fails:
- State transitions to `RECOVERY`.
- `RecoveryPlanner` diagnoses failure cause (`TIMEOUT`, `VERIFICATION_FAILURE`, `SAFETY_VIOLATION`, `APP_CRASH`, `OCR_FAILURE`).
- Dispatches remedial recovery action (e.g., dismissing unexpected dialog via `ESC`, taskbar fallback, start menu lookup).
- If consecutive failures exceed threshold, escalates to `ERROR` and triggers `TeacherAI` for lesson generation.

---

## 3. Vision Subsystem (PaddleOCR Multi-Version Adapter)

The perceptual pipeline supports dual runtime generations:
- **PaddleOCR 3.x (PaddleX architecture)**: Initializes `device='cpu'|'gpu'`, disables document unwarping (`use_doc_unwarping=False`) to avoid 500MB unnecessary document model downloads, and disables OneDNN on CPU (`enable_mkldnn=False`) to bypass the known PIR instruction bug.
- **PaddleOCR 2.x (Legacy architecture)**: Automatically falls back to `use_gpu` and `use_angle_cls`.
- **Process Isolation**: Workloads can execute asynchronously inside `IsolatedOCRClient` via Python `multiprocessing` (spawn context), isolating the main asyncio loop from GIL stalls.

---

## 4. Application Resolution Engine

`WindowsAppResolver` inspects four distinct levels before executing an application:
1. **Registry App Paths**: Inspects `HKLM\Software\Microsoft\Windows\CurrentVersion\App Paths` and `HKCU\Software\Microsoft\Windows\CurrentVersion\App Paths` for exact registered binaries.
2. **Standard Installation Directories**: Resolves standard Program Files, Program Files (x86), and LocalAppData paths.
3. **System PATH**: Resolves binaries via `shutil.which`.
4. **Protocol / URI Fallback**: Fallback to Windows URI schemes (e.g. `vscode://`, `chrome://`).
