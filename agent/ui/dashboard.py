"""Chat interface routed through the registered workflow runtime."""

import asyncio
import re
import threading
import tkinter as tk
from typing import Any, Optional

try:
    import customtkinter as ctk
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    CTK_AVAILABLE = True
except ImportError:
    CTK_AVAILABLE = False

from agent.core.engine import AgentEngine
from agent.logger import logger


class AgentDashboard:
    """Chat UI that delegates intent routing and execution to AgentEngine's workflow runtime."""

    _APP_LABELS = {
        "chrome": "Chrome",
        "msedge": "Edge",
        "code": "VS Code",
        "explorer": "Explorer",
        "notepad": "Notepad",
        "copilot": "Copilot",
        "settings": "Settings",
        "wps": "WPS",
        "wps office": "WPS Office",
    }
    _SCREEN_READ_REQUESTS = {
        "read screen", "read the screen", "what is on screen",
        "read text on screen", "read text on the screen",
        "what's on screen", "đọc màn hình", "đọc chữ trên màn hình",
        "đọc text trên màn hình", "đọc text trên screen",
    }

    def __init__(self, engine: Optional[AgentEngine] = None):
        self.engine = engine or AgentEngine()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._busy = False
        self._chat_active = False
        self._chat_cancelled = threading.Event()
        self._placeholder = "Nhập lệnh..."
        self._placeholder_active = False

        self.root = ctk.CTk() if CTK_AVAILABLE else tk.Tk()
        self.root.title("Desktop AI Agent")
        self.root.geometry("720x640")
        self.root.minsize(520, 420)

        self._build_ui()
        self.engine.add_step_callback(self._on_engine_log)
        self._append_message(
            "Agent",
            "Chào bạn! 👋 Mình là Desktop AI Agent.\n"
            "Mình có thể giúp bạn mở ứng dụng, tìm kiếm Google, đọc màn hình bằng OCR, hoặc gõ văn bản tự động.\n"
            "Bạn cần mình hỗ trợ việc gì nào?"
        )

    def _build_ui(self) -> None:
        if CTK_AVAILABLE:
            top_bar = ctk.CTkFrame(self.root, corner_radius=0)
            top_bar.pack(fill="x")
            ctk.CTkLabel(
                top_bar,
                text="Desktop AI Agent",
                font=ctk.CTkFont(size=18, weight="bold"),
            ).pack(side="left", padx=16, pady=12)
            self.status_lbl = ctk.CTkLabel(top_bar, text="Status: Ready")
            self.status_lbl.pack(side="right", padx=16, pady=12)

            self.chat_box = ctk.CTkTextbox(
                self.root, wrap="word", font=ctk.CTkFont(size=14)
            )
            self.chat_box.pack(fill="both", expand=True, padx=14, pady=12)
            self.chat_box.configure(state="disabled")

            input_frame = ctk.CTkFrame(self.root, fg_color="transparent")
            input_frame.pack(fill="x", padx=14, pady=(0, 14))
            self.command_input = ctk.CTkEntry(
                input_frame,
                placeholder_text=self._placeholder,
                height=42,
            )
            self.command_input.pack(side="left", fill="x", expand=True, padx=(0, 10))
            self.send_btn = ctk.CTkButton(
                input_frame, text="Send", width=88, height=42, command=self.send_message
            )
            self.send_btn.pack(side="right")
            self.stop_btn = ctk.CTkButton(
                input_frame, text="Stop", width=76, height=42,
                command=self.stop_agent, state="disabled",
            )
            self.stop_btn.pack(side="right", padx=(0, 8))
        else:
            top_bar = tk.Frame(self.root, bg="#202020")
            top_bar.pack(fill="x")
            tk.Label(
                top_bar, text="Desktop AI Agent", bg="#202020", fg="white",
                font=("Segoe UI", 15, "bold"),
            ).pack(side="left", padx=16, pady=12)
            self.status_lbl = tk.Label(top_bar, text="Status: Ready", bg="#202020", fg="white")
            self.status_lbl.pack(side="right", padx=16, pady=12)

            chat_frame = tk.Frame(self.root)
            chat_frame.pack(fill="both", expand=True, padx=14, pady=12)
            scrollbar = tk.Scrollbar(chat_frame)
            scrollbar.pack(side="right", fill="y")
            self.chat_box = tk.Text(
                chat_frame, wrap="word", font=("Segoe UI", 11),
                yscrollcommand=scrollbar.set, state="disabled",
            )
            self.chat_box.pack(side="left", fill="both", expand=True)
            scrollbar.configure(command=self.chat_box.yview)

            input_frame = tk.Frame(self.root)
            input_frame.pack(fill="x", padx=14, pady=(0, 14))
            self.command_input = tk.Entry(input_frame, font=("Segoe UI", 11))
            self.command_input.pack(side="left", fill="x", expand=True, padx=(0, 10), ipady=8)
            self.command_input.insert(0, self._placeholder)
            self._placeholder_active = True
            self.command_input.bind("<FocusIn>", self._clear_placeholder)
            self.command_input.bind("<FocusOut>", self._restore_placeholder)
            self.send_btn = tk.Button(input_frame, text="Send", width=10, command=self.send_message)
            self.send_btn.pack(side="right")
            self.stop_btn = tk.Button(
                input_frame, text="Stop", width=8, command=self.stop_agent, state="disabled"
            )
            self.stop_btn.pack(side="right", padx=(0, 8))

        self.command_input.bind("<Return>", self._on_enter)
        if CTK_AVAILABLE:
            self.command_input.focus_set()

    def _append_message(self, speaker: str, text: str) -> None:
        def update() -> None:
            try:
                self.chat_box.configure(state="normal")
                message = str(text or "").strip()
                self.chat_box.insert("end", f"{speaker}:\n{message}\n\n")
                self.chat_box.see("end")
                self.chat_box.configure(state="disabled")
            except Exception as exc:
                logger.error(f"[Dashboard] Could not append chat message: {exc}")

        self.root.after(0, update)

    def _set_status(self, text: str) -> None:
        def update() -> None:
            if CTK_AVAILABLE:
                self.status_lbl.configure(text=f"Status: {text}")
            else:
                self.status_lbl.config(text=f"Status: {text}")
        self.root.after(0, update)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        if CTK_AVAILABLE:
            self.send_btn.configure(state=state)
            self.stop_btn.configure(state="normal" if busy else "disabled")
            self.command_input.configure(state=state)
        else:
            self.send_btn.config(state=state)
            self.stop_btn.config(state="normal" if busy else "disabled")
            self.command_input.config(state=state)
        self._set_status("Working..." if busy else "Ready")
        if not busy:
            if not CTK_AVAILABLE and not self.command_input.get().strip():
                self.command_input.insert(0, self._placeholder)
                self._placeholder_active = True
            if CTK_AVAILABLE:
                self.command_input.focus_set()

    def _on_enter(self, _event: Any) -> str:
        self.send_message()
        return "break"

    def _clear_placeholder(self, _event: Any = None) -> None:
        if not CTK_AVAILABLE and self._placeholder_active:
            self.command_input.delete(0, "end")
            self._placeholder_active = False

    def _restore_placeholder(self, _event: Any = None) -> None:
        if not CTK_AVAILABLE and not self.command_input.get().strip():
            self.command_input.insert(0, self._placeholder)
            self._placeholder_active = True

    def send_message(self) -> None:
        if self._busy:
            return
        goal = self.command_input.get().strip()
        if not goal or self._placeholder_active or goal == self._placeholder:
            return

        self.command_input.delete(0, "end")
        self._placeholder_active = False
        self._append_message("You", goal)
        if goal.startswith(("/propose ", "/approve ", "/run ", "/reject ")):
            self._set_busy(True)
            self._worker_thread = threading.Thread(target=self._run_workflow_command, args=(goal,), daemon=True)
            self._worker_thread.start()
            return
        is_chitchat = bool(re.match(r"^\s*(?:hi|hello|hey|chào|chao|alo|hế lô|hé lô|ê\b|ơi\b|cảm ơn|thank)\b", goal, flags=re.IGNORECASE))
        if not is_chitchat:
            self._append_message("Agent", "⏳ Đang phân tích yêu cầu...")
        self._set_busy(True)

        def run_request() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.loop = loop
            request = None
            result = None
            error_text = ""
            try:
                request, result = loop.run_until_complete(self.engine.process_request(
                    goal,
                    on_chat_start=lambda: self.root.after(0, self._begin_stream_message),
                    on_chat_token=lambda token: self.root.after(0, lambda part=token: self._append_stream_token(part)),
                ))
            except Exception as exc:
                error_text = str(exc)
                logger.exception(f"[Dashboard] Workflow request failed: {exc}")
            finally:
                loop.close()
                self.root.after(0, lambda: self._finish_workflow_request(request, result, error_text))

        self._worker_thread = threading.Thread(target=run_request, daemon=True)
        self._worker_thread.start()

    def _run_workflow_command(self, command: str) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        error_text = ""
        output = ""
        try:
            operation, _, argument = command.partition(" ")
            if not argument.strip():
                raise ValueError("Usage: /propose <request>, /approve <candidate_id>, /run <task_id>, or /reject <task_id>")
            if operation == "/propose":
                candidate = loop.run_until_complete(self.engine.propose_workflow(argument.strip()))
                output = (
                    f"Workflow draft saved for review: {candidate['candidate_id']}\n"
                    f"Name: {candidate['name']}\nSteps: {candidate['steps']}\n"
                    "It is not active. Review the candidate, then send /approve <candidate_id> to register it."
                )
            elif operation == "/approve":
                approved = loop.run_until_complete(self.engine.approve_workflow(argument.strip()))
                output = f"✅ Approved and registered workflow: {approved['name']}"
            elif operation == "/run":
                task_id = argument.strip()
                from agent.workflows.script_manager import ScriptManager
                sm = ScriptManager()
                res = sm.execute_draft(task_id)
                if res["success"]:
                    output = f"✅ Thực thi thành công script '{task_id}' ({res['duration_seconds']}s):\n\n```\n{res['output']}\n```"
                else:
                    output = f"❌ Thực thi script '{task_id}' thất bại:\n\n```\n{res['output']}\n```"
            elif operation == "/reject":
                task_id = argument.strip()
                from agent.workflows.script_manager import ScriptManager
                sm = ScriptManager()
                if sm.delete_draft(task_id):
                    output = f"🗑️ Đã xóa bản thảo script '{task_id}'."
                else:
                    output = f"⚠️ Không tìm thấy bản thảo '{task_id}' để xóa."
            else:
                raise ValueError(f"Unknown command: {operation}")
        except Exception as exc:
            error_text = str(exc)
            logger.exception(f"[Dashboard] Workflow management command failed: {exc}")
        finally:
            loop.close()
            self.root.after(0, lambda: self._finish_workflow_command(output, error_text))

    def _finish_workflow_command(self, output: str, error_text: str) -> None:
        self._append_message("Agent", f"❌ {error_text}" if error_text else output)
        self._set_busy(False)

    def _finish_workflow_request(self, request: Any, result: Any, error_text: str) -> None:
        if error_text:
            self._append_message("Agent", f"❌ Yêu cầu thất bại: {error_text}")
        elif request is None or result is None:
            self._append_message("Agent", "❌ Không nhận được kết quả xử lý.")
        else:
            if request.status == "CLARIFY":
                self._append_message("Agent", f"❓ {result.message}")
                if result.error:
                    self._append_message("Agent", f"Lưu ý: {result.error}")
            elif request.status == "NO_MATCH":
                self._append_message("Agent", result.message)
                if result.error:
                    self._append_message("Agent", result.error)
            elif request.workflow != "CHAT":
                prefix = "✅ " if result.success else "❌ "
                self._append_message("Agent", prefix + result.message)
                if result.error:
                    self._append_message("Agent", result.error)
        self._set_busy(False)

    def _start_chat_stream(self, message: str) -> None:
        self._set_busy(True)
        self._chat_active = True
        self._chat_cancelled.clear()
        self._begin_stream_message()

        def run_chat() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.loop = loop
            error_text = ""

            async def consume() -> None:
                async for token in self.engine.stream_chat(message):
                    if self._chat_cancelled.is_set():
                        break
                    self.root.after(0, lambda part=token: self._append_stream_token(part))

            try:
                loop.run_until_complete(consume())
            except Exception as exc:
                error_text = str(exc)
                logger.exception(f"[Dashboard] Chat streaming failed: {exc}")
            finally:
                loop.close()
                self.root.after(0, lambda: self._finish_chat_stream(error_text))

        self._worker_thread = threading.Thread(target=run_chat, daemon=True)
        self._worker_thread.start()

    def _begin_stream_message(self) -> None:
        try:
            self.chat_box.configure(state="normal")
            self.chat_box.insert("end", "Agent:\n")
            self.chat_box.see("end")
            self.chat_box.configure(state="disabled")
        except Exception as exc:
            logger.error(f"[Dashboard] Could not start streamed message: {exc}")

    def _append_stream_token(self, token: str) -> None:
        try:
            self.chat_box.configure(state="normal")
            self.chat_box.insert("end", token)
            self.chat_box.see("end")
            self.chat_box.configure(state="disabled")
        except Exception as exc:
            logger.error(f"[Dashboard] Could not display streamed token: {exc}")

    def _finish_chat_stream(self, error_text: str) -> None:
        try:
            self.chat_box.configure(state="normal")
            if error_text:
                self.chat_box.insert("end", f"\n\n⚠️ {error_text}\n\n")
            else:
                self.chat_box.insert("end", "\n\n")
            self.chat_box.see("end")
            self.chat_box.configure(state="disabled")
        except Exception as exc:
            logger.error(f"[Dashboard] Could not finish streamed message: {exc}")
        self._chat_active = False
        self._set_busy(False)

    def _read_screen_text(self) -> None:
        """Read visible screen text directly, without starting the agent workflow."""
        text = ""
        error_text = ""
        try:
            frame = self.engine.capture.capture_frame()
            result = self.engine.ocr.extract_text(frame)
            text = result.get("full_text", "").strip()
        except Exception as exc:
            error_text = str(exc)
            logger.exception(f"[Dashboard] Screen text reading failed: {exc}")
        finally:
            self.root.after(0, lambda: self._finish_screen_read(text, error_text))

    def _finish_screen_read(self, text: str, error_text: str) -> None:
        if error_text:
            self._append_message("Agent", f"❌ Could not read screen text.\n{error_text}")
        elif text:
            self._append_message("Agent", text)
        else:
            self._append_message("Agent", "I couldn't detect any text on the screen.")
        self._set_busy(False)

    def _finish_goal(self, success: bool, known_app: Any, error_text: str) -> None:
        if success and known_app:
            app_name = self._APP_LABELS.get(known_app[0], known_app[0].title())
            self._append_message("Agent", f"✅ {app_name} launched successfully")
        elif success:
            self._append_message("Agent", "✅ Goal completed successfully")
        else:
            message = "❌ I couldn't complete that request."
            if error_text:
                message += f"\n{error_text}"
            self._append_message("Agent", message)
        self._set_busy(False)

    def stop_agent(self) -> None:
        if not self._busy:
            return
        if self._chat_active:
            self._chat_cancelled.set()
            self._append_message("Agent", "Stopping response...")
            self._set_status("Stopping...")
            return
        self.engine.stop()
        self._append_message("Agent", "Stopping the current task...")
        self._set_status("Stopping...")

    def _on_engine_log(self, message: str, state: Any) -> None:
        """Show useful FSM progress in chat for complex goals."""
        visible_markers = (
            "Observation complete", "Proposed Action", "Action executed",
            "verification", "Goal ", "Recovery Strategy", "failed",
        )
        if any(marker.casefold() in message.casefold() for marker in visible_markers):
            self._append_message("Agent", message)

    def run(self) -> None:
        self.root.mainloop()
