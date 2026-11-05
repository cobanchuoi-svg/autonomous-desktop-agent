"""Windows image clipboard and WPS paste action."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ImageCopyResult:
    success: bool
    message: str


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def copy_image_to_wps(
    image_path: str,
    *,
    wps_title: str = "WPS",
    window_controller: Any,
) -> ImageCopyResult:
    """Put an image on the Windows clipboard, focus WPS, and paste it."""
    path = Path(image_path).expanduser()
    if not path.is_file():
        return ImageCopyResult(False, f"Image does not exist: {path}")
    if os.name != "nt":
        return ImageCopyResult(False, "Copying an image into WPS requires Windows.")

    image_literal = _powershell_literal(str(path.resolve()))
    script = (
        "Add-Type -AssemblyName System.Drawing; "
        "Add-Type -AssemblyName System.Windows.Forms; "
        f"$img=[System.Drawing.Image]::FromFile({image_literal}); "
        "[System.Windows.Forms.Clipboard]::SetImage($img); "
        "$img.Dispose()"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ImageCopyResult(False, f"Could not prepare image clipboard: {exc}")
    if completed.returncode != 0:
        return ImageCopyResult(False, completed.stderr.strip() or "Could not put image on clipboard.")
    if not window_controller.activate_window(wps_title):
        return ImageCopyResult(False, f"Could not focus {wps_title}.")
    try:
        import pyautogui

        pyautogui.hotkey("ctrl", "v")
    except Exception as exc:
        return ImageCopyResult(False, f"Could not paste image into {wps_title}: {exc}")
    return ImageCopyResult(True, f"Image pasted into {wps_title}.")
