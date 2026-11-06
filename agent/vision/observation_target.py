"""User-selected desktop window target for focused OCR observation."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Optional

from agent.vision.window_surface import WindowSurface


@dataclass(frozen=True)
class ObservationTarget:
    window_id: str
    title: str
    rect: tuple[int, int, int, int]

    @property
    def label(self) -> str:
        return self.title or self.window_id

    def as_surface(self) -> WindowSurface:
        return WindowSurface(self.window_id, self.title, self.rect, is_popup=False)


class ObservationTargetSelector:
    """Enumerate visible app windows and focus only an explicitly selected one."""

    def list_targets(self) -> list[ObservationTarget]:
        try:
            import pygetwindow

            items: list[ObservationTarget] = []
            seen: set[str] = set()
            for window in pygetwindow.getAllWindows():
                title = str(getattr(window, "title", "") or "").strip()
                width, height = int(window.width), int(window.height)
                handle = int(getattr(window, "_hWnd"))
                if not title or width < 80 or height < 80:
                    continue
                window_id = f"hwnd_{handle:x}"
                if window_id in seen:
                    continue
                seen.add(window_id)
                items.append(ObservationTarget(
                    window_id=window_id,
                    title=title,
                    rect=(int(window.left), int(window.top), int(window.right), int(window.bottom)),
                ))
            return items
        except Exception:
            return []

    def focus(self, window_id: str) -> Optional[ObservationTarget]:
        """Focus a listed target and return refreshed bounds only on success."""
        target = next((item for item in self.list_targets() if item.window_id == window_id), None)
        if target is None:
            return None
        try:
            hwnd = int(window_id.removeprefix("hwnd_"), 16)
            user32 = ctypes.windll.user32
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            if int(user32.GetForegroundWindow()) != hwnd:
                return None
        except Exception:
            return None
        return next((item for item in self.list_targets() if item.window_id == window_id), target)
