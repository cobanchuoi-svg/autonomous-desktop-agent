"""Window orchestration for observing a foreground document with WPS in the background."""

import ctypes
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from agent.logger import logger


_SW_MAXIMIZE = 3
_HWND_BOTTOM = 1
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040


@dataclass(frozen=True)
class WindowLayoutResult:
    success: bool
    document_title: Optional[str] = None
    reason: str = ""


class DocumentWindowController:
    """Keep WPS open behind the foreground PDF/image observation window."""

    @staticmethod
    def _matches_title(title: str, query: str) -> bool:
        normalized_title = "".join(char.lower() for char in title if char.isalnum())
        normalized_query = "".join(char.lower() for char in query if char.isalnum())
        return bool(normalized_query and normalized_query in normalized_title)

    @classmethod
    def _find_window(cls, query: str):
        try:
            import pygetwindow

            windows = [
                window
                for window in pygetwindow.getAllWindows()
                if getattr(window, "visible", True)
                and cls._matches_title(getattr(window, "title", ""), query)
            ]
            return windows[0] if len(windows) == 1 else None
        except Exception as exc:
            logger.warning(f"[DocumentWindowController] Window lookup failed: {exc}")
            return None

    @staticmethod
    def _maximize_and_activate(window) -> bool:
        handle = getattr(window, "_hWnd", None)
        if not handle:
            return False
        user32 = ctypes.windll.user32
        user32.ShowWindow(handle, _SW_MAXIMIZE)
        user32.SetForegroundWindow(handle)
        return True

    @staticmethod
    def _send_to_background(window) -> bool:
        handle = getattr(window, "_hWnd", None)
        if not handle:
            return False
        user32 = ctypes.windll.user32
        return bool(
            user32.SetWindowPos(
                handle,
                _HWND_BOTTOM,
                0,
                0,
                0,
                0,
                _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
            )
        )

    def activate_window(self, title_query: str) -> bool:
        """Activate a uniquely matching window without changing its layout."""
        window = self._find_window(title_query)
        if window is None:
            return False
        handle = getattr(window, "_hWnd", None)
        if not handle:
            return False
        ctypes.windll.user32.SetForegroundWindow(handle)
        time.sleep(0.2)
        return True

    def prepare_foreground_document(
        self,
        document_path: str,
        *,
        wps_title: str = "WPS",
        timeout: float = 8.0,
    ) -> WindowLayoutResult:
        """Open a PDF/image, maximize it, and place the WPS window behind it."""
        path = Path(document_path).expanduser()
        if not path.is_file():
            return WindowLayoutResult(False, reason=f"Document does not exist: {path}")
        if os.name != "nt":
            return WindowLayoutResult(False, reason="Foreground document layout requires Windows")

        if path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}:
            return WindowLayoutResult(True, document_title=path.name)

        try:
            os.startfile(str(path))
        except OSError as exc:
            return WindowLayoutResult(False, reason=f"Could not open document: {exc}")

        deadline = time.monotonic() + max(0.5, timeout)
        document_window = None
        while time.monotonic() < deadline:
            document_window = self._find_window(path.stem)
            if document_window is not None:
                break
            time.sleep(0.15)
        if document_window is None:
            return WindowLayoutResult(False, reason=f"Could not find window for {path.name}")

        wps_window = self._find_window(wps_title)
        if wps_window is not None:
            self._send_to_background(wps_window)
        if not self._maximize_and_activate(document_window):
            return WindowLayoutResult(False, reason=f"Could not activate document window for {path.name}")
        return WindowLayoutResult(True, document_title=getattr(document_window, "title", path.name))


__all__ = ["DocumentWindowController", "WindowLayoutResult"]
