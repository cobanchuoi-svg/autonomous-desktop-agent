"""Windows image clipboard, safe paste, and Excel exporter."""

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class ImageCopyResult:
    success: bool
    message: str


def format_text_as_tsv(text: str) -> str:
    """Format multiline text into Tab-Separated Values (TSV).
    
    When pasted into Excel or WPS Sheets, tab-separated characters automatically
    populate separate columns and newlines populate separate rows.
    """
    lines = []
    for line in text.strip().splitlines():
        trimmed = line.strip()
        if not trimmed:
            continue
        # If line does not have tabs but has 2+ consecutive spaces, convert to tab
        if "\t" not in trimmed:
            line_tsv = re.sub(r" {2,}", "\t", trimmed)
        else:
            line_tsv = trimmed
        lines.append(line_tsv)
    return "\n".join(lines)


def export_text_to_excel(text: str, output_path: str) -> ImageCopyResult:
    """Export raw or TSV text directly to an Excel (.xlsx) file using openpyxl."""
    try:
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "ExtractedData"

        tsv_data = format_text_as_tsv(text)
        for line in tsv_data.splitlines():
            cells = [cell.strip() for cell in line.split("\t")]
            if cells:
                ws.append(cells)

        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        wb.save(str(target))
        return ImageCopyResult(True, f"Đã xuất file Excel thành công: {target}")
    except Exception as exc:
        return ImageCopyResult(False, f"Không thể xuất file Excel: {exc}")


def _paste_text(text: str, *, wps_title: str, window_controller: Any) -> ImageCopyResult:
    if not text.strip():
        return ImageCopyResult(False, "OCR produced no text to paste.")
    if not window_controller.activate_window(wps_title):
        return ImageCopyResult(False, f"Could not focus {wps_title}.")

    # Format text with TSV so Excel/WPS automatically separates columns and rows
    formatted_payload = format_text_as_tsv(text)

    # Put on clipboard directly with Unicode support
    try:
        import pyperclip
        pyperclip.copy(formatted_payload)
    except Exception as exc:
        return ImageCopyResult(False, f"Could not put text on clipboard: {exc}")

    time.sleep(0.25)

    try:
        import pyautogui
        pyautogui.hotkey("ctrl", "v")
    except Exception as exc:
        return ImageCopyResult(False, f"Could not paste text into {wps_title}: {exc}")

    return ImageCopyResult(True, f"OCR content pasted into {wps_title}.")


def stream_write_text_to_window(
    text: str,
    *,
    wps_title: str = "WPS",
    window_controller: Any,
    line_delay: float = 0.05,
    chunk_delay: float = 0.015,
) -> ImageCopyResult:
    """Stream text into the target window like a human or advanced AI agent (e.g., Claude Computer Use).
    
    Types text line-by-line / word-by-word into the focused document window,
    providing live visual feedback and full Vietnamese Unicode support via SendInput.
    """
    if not text.strip():
        return ImageCopyResult(False, "OCR produced no text to write.")
    if not window_controller.activate_window(wps_title):
        return ImageCopyResult(False, f"Could not focus {wps_title}.")

    time.sleep(0.25)

    from agent.actions.keyboard import KeyboardController

    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return ImageCopyResult(False, "No printable lines found in text.")

    for line_idx, line in enumerate(lines):
        trimmed = line.strip()
        words = trimmed.split(" ")
        cluster = []
        for word in words:
            cluster.append(word)
            if len(cluster) >= 3:
                chunk = " ".join(cluster) + " "
                if os.name == "nt":
                    KeyboardController._write_unicode_windows(chunk)
                else:
                    import pyautogui
                    pyautogui.write(chunk)
                cluster = []
                if chunk_delay > 0:
                    time.sleep(chunk_delay)
        if cluster:
            chunk = " ".join(cluster)
            if os.name == "nt":
                KeyboardController._write_unicode_windows(chunk)
            else:
                import pyautogui
                pyautogui.write(chunk)

        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.keybd_event(0x0D, 0, 0, 0)
            time.sleep(0.01)
            ctypes.windll.user32.keybd_event(0x0D, 0, 2, 0)
        else:
            import pyautogui
            pyautogui.press("enter")

        if line_delay > 0:
            time.sleep(line_delay)

    return ImageCopyResult(True, f"Đã gõ trực tiếp {len(lines)} dòng nội dung vào {wps_title}.")


def copy_image_content_to_wps(
    text: str,
    *,
    wps_title: str = "WPS",
    window_controller: Any,
    mode: str = "auto",
) -> ImageCopyResult:
    """Put OCR text into target window.
    
    If mode is 'stream', or 'auto' targeting a document/word/writer/notepad window,
    streams characters live like a Computer Use agent.
    If targeting a spreadsheet (sheet/excel), pastes TSV directly into grid cells.
    """
    title_lower = wps_title.lower()
    is_spreadsheet = any(kw in title_lower for kw in ["sheet", "excel", "bảng tính", "calc"])
    should_stream = mode == "stream" or (mode == "auto" and not is_spreadsheet)

    if should_stream:
        return stream_write_text_to_window(text, wps_title=wps_title, window_controller=window_controller)
    return _paste_text(text, wps_title=wps_title, window_controller=window_controller)


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
