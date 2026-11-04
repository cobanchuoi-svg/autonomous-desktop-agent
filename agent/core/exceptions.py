"""
Domain exceptions for the desktop AI agent.
"""

class AgentException(Exception):
    """Base exception for agent errors."""
    pass


class VisionException(AgentException):
    """Raised when screen capture fails."""
    pass


class OCRException(AgentException):
    """Raised when optical character recognition fails or returns invalid text."""
    pass


class OCRUnavailableError(OCRException):
    """Raised when the OCR engine (e.g. PaddleOCR) is not installed or unavailable."""
    pass


class ActionExecutionException(AgentException):
    """Raised when mouse, keyboard, or OS action fails."""
    pass


class SafetyViolationException(AgentException):
    """Raised when an action violates safety policies."""
    pass


class LLMInferenceException(AgentException):
    """Raised when local LLM inference or parsing fails."""
    pass
