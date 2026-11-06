"""
Desktop screen capture using MSS with multi-monitor support and frame buffering.
"""

import threading
import time
from typing import Dict, List, Optional
import numpy as np
from PIL import Image

try:
    from PIL import ImageGrab
except ImportError:
    ImageGrab = None

try:
    import mss
    import mss.tools
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False

from agent.core.exceptions import VisionException
from agent.vision.base import BaseScreenCapture
from agent.logger import logger


class ScreenCapture(BaseScreenCapture):
    """Captures desktop screen frames asynchronously or synchronously."""

    def __init__(self, monitor_index: int = 1, buffer_size: int = 5):
        self.monitor_index = monitor_index
        self.buffer_size = buffer_size
        self._latest_frame: Optional[Image.Image] = None
        self._latest_np: Optional[np.ndarray] = None
        self._is_capturing = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._last_frame_origin: tuple[int, int] = (0, 0)

    def get_monitors(self) -> List[Dict[str, int]]:
        """Return available monitor dimensions."""
        if MSS_AVAILABLE:
            with mss.mss() as sct:
                return list(sct.monitors)
        return [{"top": 0, "left": 0, "width": 1920, "height": 1080}]

    def capture_frame(self) -> Image.Image:
        """Capture a single frame from the specified monitor."""
        img = None
        try:
            if MSS_AVAILABLE:
                try:
                    with mss.mss() as sct:
                        monitor = sct.monitors[min(self.monitor_index, len(sct.monitors) - 1)]
                        sct_img = sct.grab(monitor)
                        self._last_frame_origin = (int(monitor["left"]), int(monitor["top"]))
                        # Convert to PIL Image (RGB)
                        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                except Exception as mss_err:
                    logger.warning(f"[ScreenCapture] MSS capture failed ({mss_err}), falling back to ImageGrab.")
                    try:
                        img = ImageGrab.grab()
                        self._last_frame_origin = (0, 0)
                    except Exception as grab_err:
                        logger.warning(f"[ScreenCapture] ImageGrab failed ({grab_err}).")

            if img is None:
                try:
                    img = ImageGrab.grab()
                    self._last_frame_origin = (0, 0)
                except Exception:
                    pass

            # Fallback if display surface is unavailable (e.g., Windows desktop locked or headless)
            if img is None:
                logger.warning("[ScreenCapture] Desktop display surface unavailable. Producing fallback frame.")
                img = Image.new("RGB", (1920, 1080), color=(40, 40, 40))

            with self._lock:
                self._latest_frame = img
                self._latest_np = np.array(img)

            return img
        except Exception as e:
            raise VisionException(f"Screen capture failed: {e}") from e

    def last_frame_origin(self) -> tuple[int, int]:
        """Desktop coordinate represented by pixel (0, 0) of the latest frame."""
        return self._last_frame_origin

    def get_latest_frame(self) -> Image.Image:
        """Get the latest buffered frame, capturing one if none exists."""
        with self._lock:
            if self._latest_frame is not None:
                return self._latest_frame.copy()
        return self.capture_frame()

    def get_latest_array(self) -> np.ndarray:
        """Get the latest frame as a numpy array."""
        with self._lock:
            if self._latest_np is not None:
                return self._latest_np.copy()
        self.capture_frame()
        with self._lock:
            assert self._latest_np is not None
            return self._latest_np.copy()

    def start_capture(self, interval: float = 1.0) -> None:
        """Start background capture loop."""
        if self._is_capturing:
            return
        self._is_capturing = True

        def _loop():
            logger.info(f"[ScreenCapture] Background capture started (interval: {interval}s)")
            while self._is_capturing:
                try:
                    self.capture_frame()
                except Exception as e:
                    logger.error(f"[ScreenCapture] Loop error: {e}")
                time.sleep(interval)
            logger.info("[ScreenCapture] Background capture stopped")

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop_capture(self) -> None:
        """Stop background capture loop."""
        self._is_capturing = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
