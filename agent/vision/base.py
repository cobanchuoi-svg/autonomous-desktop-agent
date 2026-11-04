"""
Abstract interfaces for Vision and OCR perceptual components.
Clean Architecture Perceptual Port.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List
from PIL import Image
from agent.vision.parser import UIElement


class BaseScreenCapture(ABC):
    """Abstract interface for screen observation."""

    @abstractmethod
    def capture_frame(self) -> Image.Image:
        """Capture a single frame from the desktop."""
        pass

    @abstractmethod
    def get_latest_frame(self) -> Image.Image:
        """Return the most recently buffered screen frame."""
        pass


class BaseOCRProcessor(ABC):
    """Abstract interface for Optical Character Recognition."""

    @abstractmethod
    def extract_text(self, image: Image.Image) -> Dict[str, Any]:
        """Extract text and detected bounding boxes from an image frame."""
        pass

    def is_available(self) -> bool:
        """Check if the underlying OCR engine is installed and operational."""
        return True

    @abstractmethod
    def clean_text(self, text: str) -> str:
        """Normalize and filter raw OCR text."""
        pass

    @abstractmethod
    def find_ui_elements(self, image: Image.Image, query: str) -> List[UIElement]:
        """Locate UI elements matching a text pattern."""
        pass
