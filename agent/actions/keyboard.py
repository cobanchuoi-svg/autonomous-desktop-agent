"""
Keyboard controller leveraging PyAutoGUI and pynput for typing, key presses, and shortcuts.
"""

import time
import os
import ctypes
from ctypes import wintypes
from typing import List, Union
from agent.actions.base import ActionResult, ActionType
from agent.logger import logger

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except Exception:
    PYAUTOGUI_AVAILABLE = False


class KeyboardController:
    """Controls typing text, individual key presses, and complex key combinations."""

    def __init__(self, default_interval: float = 0.05):
        self.default_interval = default_interval

    @staticmethod
    def _paste_unicode_windows(text: str, settle_seconds: float = 0.2) -> bool:
        """Paste Unicode through the clipboard, preserving plain-text clipboard contents."""
        if os.name != "nt" or not PYAUTOGUI_AVAILABLE:
            return False
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        cf_unicode_text = 13
        gmem_moveable = 0x0002
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
        user32.EnumClipboardFormats.restype = wintypes.UINT
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL

        previous_text = None
        supported_clipboard = False
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if user32.OpenClipboard(None):
                try:
                    formats = []
                    current_format = user32.EnumClipboardFormats(0)
                    while current_format:
                        formats.append(current_format)
                        current_format = user32.EnumClipboardFormats(current_format)
                    # Preserve simple text clips; do not destroy rich, image, file, or app data.
                    plain_text_formats = {1, cf_unicode_text, 16}  # CF_TEXT, CF_UNICODETEXT, CF_LOCALE
                    if not formats or (cf_unicode_text in formats and set(formats) <= plain_text_formats):
                        supported_clipboard = True
                        handle = user32.GetClipboardData(cf_unicode_text)
                        if handle:
                            pointer = kernel32.GlobalLock(handle)
                            if pointer:
                                try:
                                    previous_text = ctypes.wstring_at(pointer)
                                finally:
                                    kernel32.GlobalUnlock(handle)
                    break
                finally:
                    user32.CloseClipboard()
            time.sleep(0.02)
        if not supported_clipboard:
            return False

        payload = (text + "\0").encode("utf-16-le")
        memory = kernel32.GlobalAlloc(gmem_moveable, len(payload))
        if not memory:
            return False
        pointer = kernel32.GlobalLock(memory)
        if not pointer:
            return False
        ctypes.memmove(pointer, payload, len(payload))
        kernel32.GlobalUnlock(memory)

        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if user32.OpenClipboard(None):
                try:
                    if not user32.EmptyClipboard() or not user32.SetClipboardData(cf_unicode_text, memory):
                        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
                        kernel32.GlobalFree(memory)
                        return False
                    memory = None  # Clipboard owns the global memory after SetClipboardData.
                finally:
                    user32.CloseClipboard()
                break
            time.sleep(0.02)
        if memory:
            kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalFree(memory)
            return False

        try:
            pyautogui.hotkey("ctrl", "v")
            time.sleep(max(0.15, settle_seconds))
        finally:
            restore = (previous_text or "").encode("utf-16-le") + b"\0\0"
            restore_memory = kernel32.GlobalAlloc(gmem_moveable, len(restore))
            if restore_memory:
                restore_pointer = kernel32.GlobalLock(restore_memory)
                if restore_pointer:
                    ctypes.memmove(restore_pointer, restore, len(restore))
                    kernel32.GlobalUnlock(restore_memory)
                    if user32.OpenClipboard(None):
                        try:
                            if user32.EmptyClipboard() and user32.SetClipboardData(cf_unicode_text, restore_memory):
                                restore_memory = None
                        finally:
                            user32.CloseClipboard()
                if restore_memory:
                    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
                    kernel32.GlobalFree(restore_memory)
        return True

    @staticmethod
    def _write_unicode_windows(text: str) -> None:
        """Inject Unicode text through SendInput so Vietnamese is preserved."""
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t),
            ]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t),
            ]

        class INPUT_UNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]

        keyeventf_keyup = 0x0002
        keyeventf_unicode = 0x0004
        units = text.encode("utf-16-le")
        count = len(units) // 2
        inputs = (INPUT * (count * 2))()
        for index in range(count):
            unit = units[index * 2] | (units[index * 2 + 1] << 8)
            inputs[index * 2].type = 1  # INPUT_KEYBOARD
            inputs[index * 2].union.ki = KEYBDINPUT(0, unit, keyeventf_unicode, 0, 0)
            inputs[index * 2 + 1].type = 1
            inputs[index * 2 + 1].union.ki = KEYBDINPUT(0, unit, keyeventf_unicode | keyeventf_keyup, 0, 0)

        send_input = ctypes.windll.user32.SendInput
        send_input.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        send_input.restype = wintypes.UINT
        chunk_units = 32
        start = 0
        while start < count:
            end = min(count, start + chunk_units)
            # Keep UTF-16 surrogate pairs together if the text includes emoji.
            if end < count:
                last_unit = units[(end - 1) * 2] | (units[(end - 1) * 2 + 1] << 8)
                next_unit = units[end * 2] | (units[end * 2 + 1] << 8)
                if 0xD800 <= last_unit <= 0xDBFF and 0xDC00 <= next_unit <= 0xDFFF:
                    end -= 1
            event_start = start * 2
            event_count = (end - start) * 2
            chunk = ctypes.cast(
                ctypes.byref(inputs, event_start * ctypes.sizeof(INPUT)),
                ctypes.POINTER(INPUT),
            )
            sent = send_input(event_count, chunk, ctypes.sizeof(INPUT))
            if sent != event_count:
                raise OSError(f"Windows accepted {sent} of {event_count} Unicode keyboard events in a chunk.")
            start = end
            time.sleep(0.005)

    def write(self, text: str, interval: float = 0.05) -> ActionResult:
        """Type characters sequentially into the currently focused window."""
        start = time.perf_counter()
        method = "typed"
        try:
            if PYAUTOGUI_AVAILABLE:
                if os.name == "nt" and not text.isascii():
                    if not self._paste_unicode_windows(text, interval or self.default_interval):
                        raise RuntimeError(
                            "Unicode text was not pasted because the clipboard contains unsupported data; "
                            "refusing the unreliable SendInput fallback."
                        )
                    method = "pasted"
                else:
                    pyautogui.write(
                        text,
                        interval=self.default_interval if interval is None else interval,
                    )
            else:
                logger.info(f"[Keyboard Simulation] Typed: '{text}'")

            elapsed = time.perf_counter() - start
            return ActionResult(
                success=True,
                action_type=ActionType.WRITE,
                message=f"{method.title()} {len(text)} characters",
                execution_time=elapsed,
            )
        except Exception as e:
            elapsed = time.perf_counter() - start
            logger.error(f"[KeyboardController] Write failed: {e}")
            return ActionResult(
                success=False,
                action_type=ActionType.WRITE,
                error=str(e),
                execution_time=elapsed,
            )

    def press(self, key: str) -> ActionResult:
        """Press and release a single key (e.g. 'enter', 'tab', 'esc')."""
        start = time.perf_counter()
        try:
            if PYAUTOGUI_AVAILABLE:
                pyautogui.press(key)
            else:
                logger.info(f"[Keyboard Simulation] Pressed key: '{key}'")

            elapsed = time.perf_counter() - start
            return ActionResult(
                success=True,
                action_type=ActionType.PRESS,
                message=f"Pressed key '{key}'",
                execution_time=elapsed,
            )
        except Exception as e:
            elapsed = time.perf_counter() - start
            logger.error(f"[KeyboardController] Press failed: {e}")
            return ActionResult(
                success=False,
                action_type=ActionType.PRESS,
                error=str(e),
                execution_time=elapsed,
            )

    def hotkey(self, *keys: str) -> ActionResult:
        """Trigger a shortcut combination (e.g. 'ctrl', 'c' or 'win', 'r')."""
        start = time.perf_counter()
        try:
            if PYAUTOGUI_AVAILABLE:
                pyautogui.hotkey(*keys)
            else:
                logger.info(f"[Keyboard Simulation] Hotkey: {' + '.join(keys)}")

            elapsed = time.perf_counter() - start
            return ActionResult(
                success=True,
                action_type=ActionType.HOTKEY,
                message=f"Executed shortcut: {' + '.join(keys)}",
                execution_time=elapsed,
            )
        except Exception as e:
            elapsed = time.perf_counter() - start
            logger.error(f"[KeyboardController] Hotkey failed: {e}")
            return ActionResult(
                success=False,
                action_type=ActionType.HOTKEY,
                error=str(e),
                execution_time=elapsed,
            )
