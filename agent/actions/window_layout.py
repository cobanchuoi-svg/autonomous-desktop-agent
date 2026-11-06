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
        normalized_query = "".join(
            char.lower() for char in query.replace(r"\_", "_") if char.isalnum()
        )
        if normalized_query and normalized_query in normalized_title:
            return True
        q_lower = query.lower()
        t_lower = title.lower()
        if "wps" in q_lower and "wps" in t_lower:
            return True
        if "word" in q_lower and ("word" in t_lower or "winword" in t_lower or "wps" in t_lower):
            return True
        if "excel" in q_lower and any(k in t_lower for k in ("excel", "sheet", "spreadsheet", "et")):
            return True
        if any(k in q_lower for k in ("sheet", "spreadsheet", "bảng tính")):
            if any(k in t_lower for k in ("sheet", "spreadsheet", "excel", "bảng tính", "et", "bảng")):
                return True
        return False

    @staticmethod
    def _wps_window_score(title: str) -> int:
        """Rank editable WPS documents above WPS photo viewers."""
        normalized = title.casefold()
        score = 0
        if "wps office" in normalized:
            score += 100
        if any(kind in normalized for kind in ("writer", "spreadsheet", "presentation")):
            score += 20
        if any(kind in normalized for kind in ("photos", "photo viewer", "image viewer")):
            score -= 100
        return score

    @classmethod
    def _find_window(cls, query: str, *, prefer_wps: bool = False):
        try:
            import pygetwindow

            windows = [
                window
                for window in pygetwindow.getAllWindows()
                if getattr(window, "visible", True)
                and cls._matches_title(getattr(window, "title", ""), query)
            ]
            if len(windows) == 1:
                return windows[0]
            if windows:
                normalized_titles = {
                    "".join(
                        char.lower()
                        for char in getattr(window, "title", "")
                        if char.isalnum()
                    )
                    for window in windows
                }
                if len(normalized_titles) == 1:
                    return windows[0]
            if prefer_wps and windows:
                ranked = sorted(
                    windows,
                    key=lambda window: cls._wps_window_score(getattr(window, "title", "")),
                    reverse=True,
                )
                # Always return best-ranked WPS window (even if scores are tied)
                return ranked[0]
            # Fallback: return first matching window
            if windows:
                return windows[0]
            return None
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
        """Activate a matching window without changing its layout."""
        window = self._find_window(title_query, prefer_wps=True)
        if window is None:
            for alt in ["wps", "excel", "sheet", "word", "office"]:
                window = self._find_window(alt, prefer_wps=True)
                if window is not None:
                    break
        if window is None:
            return False
        handle = getattr(window, "_hWnd", None)
        if not handle:
            return False
        user32 = ctypes.windll.user32
        user32.ShowWindow(handle, 9)  # SW_RESTORE
        user32.SetForegroundWindow(handle)
        time.sleep(0.3)
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

        # Headless mode for image files: process in memory without popping up photo viewer
        if path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".pdf"}:
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

        wps_window = self._find_window(wps_title, prefer_wps=wps_title.casefold() in {"wps", "wps office"})
        if wps_window is not None:
            self._send_to_background(wps_window)
        if not self._maximize_and_activate(document_window):
            return WindowLayoutResult(False, reason=f"Could not activate document window for {path.name}")
        return WindowLayoutResult(True, document_title=getattr(document_window, "title", path.name))


__all__ = ["DocumentWindowController", "WindowLayoutResult"]
