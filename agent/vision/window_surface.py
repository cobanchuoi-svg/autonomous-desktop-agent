"""Best-effort foreground-window metadata for distinguishing popups from the desktop."""

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from agent.vision.parser import UIElement


@dataclass(frozen=True)
class WindowSurface:
    window_id: str
    title: str
    rect: Tuple[int, int, int, int]
    is_popup: bool
    class_name: str = ""

    def contains(self, x: int, y: int) -> bool:
        left, top, right, bottom = self.rect
        return left <= x < right and top <= y < bottom


class WindowSurfaceDetector:
    """Reads native foreground window bounds without OCR or a subprocess."""

    def current(self) -> Optional[WindowSurface]:
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            user32.GetWindowRect.restype = wintypes.BOOL
            user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetWindowTextW.restype = ctypes.c_int
            user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetClassNameW.restype = ctypes.c_int
            user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetWindow.restype = wintypes.HWND
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None
            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
            title_buffer = ctypes.create_unicode_buffer(512)
            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
            user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
            get_window_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_window_long.restype = ctypes.c_ssize_t
            style = int(get_window_long(hwnd, -16)) & 0xFFFFFFFF
            owner = user32.GetWindow(hwnd, 4)  # GW_OWNER
            class_name = class_buffer.value
            is_popup = bool(owner) or bool(style & 0x80000000) or class_name in {"#32768", "#32770"}
            return WindowSurface(
                window_id=f"hwnd_{int(hwnd):x}",
                title=title_buffer.value,
                rect=(int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)),
                is_popup=is_popup,
                class_name=class_name,
            )
        except Exception:
            return None

    @staticmethod
    def tag_elements(elements: Iterable[UIElement], window: Optional[WindowSurface]) -> list[UIElement]:
        tagged = []
        for element in elements:
            inside = window is not None and window.contains(element.center_x, element.center_y)
            tagged.append(element.model_copy(update={
                "surface": "popup" if inside and window.is_popup else "desktop",
                "container_id": window.window_id if inside and window else None,
                "window_title": window.title if inside and window else None,
            }))
        return tagged
