# Current Bug List & Known Blockers

**Date**: 2026-10-27 (local environment notes)
**Target Version**: 1.0.0-rc1

---

## 1. Current Bug List

### Bug #1: Goal Planner Context Carryover / Cross-Task Contamination
- **Severity**: High
- **Description**: When executing sequential goals (e.g. running "Open Chrome" after a prior task or session), `MemoryManager._load_active_state` can resume tasks from an uncompleted prior goal if the previous session exited abnormally without marking the goal completed.
- **Symptom**: In Task 1 ("Open Chrome"), the system previously attempted to resolve actions associated with VS Code because incomplete tasks from an earlier test remained active in SQLite.
- **Mitigation / Workaround**: The agent now explicitly clears or marks prior active goals completed when initializing a clean session or resetting the database.

### Bug #2: PyAutoGUI Corner Fail-Safe Triggering in Background Runs
- **Severity**: Medium
- **Description**: In Windows desktop environments where the mouse cursor is moved by background automation or parked at (0, 0), PyAutoGUI's built-in fail-safe triggers an exception:
  `PyAutoGUI fail-safe triggered from mouse moving to a corner of the screen`.
- **Status**: Identified in `KeyboardController` / `MouseController`.
- **Mitigation**: Move cursor towards the center screen or configure safe coordinates before write actions.

### Bug #3: VS Code Not Installed in Standard Path
- **Severity**: Low (Environment Specific)
- **Description**: `WindowsAppResolver` searches Registry App Paths, Program Files, LocalAppData, and PATH for `Code.exe`. In environments where VS Code is not installed (or only alternative IDEs like OpenCode are present), launching `code` fails gracefully and reports application not found.

---

## 2. Known Blockers

### Blocker #1: Windows GDI Display Surface Locking
- **Category**: Operating System Security / Environment
- **Description**: When running in an unattended/locked Windows desktop or disconnected remote session, the Windows kernel disables the GDI screen surface, causing `BitBlt` in MSS to fail (`Windows graphics function failed: BitBlt`).
- **Resolution Implemented**: `ScreenCapture` implements a resilient multi-tier fallback: MSS -> `PIL.ImageGrab` -> fallback frame. Autonomous execution continues without unhandled exceptions.

### Blocker #2: Sandboxed Network Isolation for Model Downloads
- **Category**: Sandboxing / Infrastructure
- **Description**: PaddleOCR 3.x may contact model repositories (`huggingface.co`, `modelscope.cn`, `bcebos.com`) if official models are not already cached under `%USERPROFILE%\.paddlex\official_models`.
- **Status**: Resolved only on the original development machine. The model cache is not included in this repository; new installations must download compatible model files.
