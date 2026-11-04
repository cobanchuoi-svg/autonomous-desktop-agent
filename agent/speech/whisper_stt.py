"""Optional local Whisper speech-to-text input using faster-whisper."""

import threading
import time
from typing import Callable, Optional


class WhisperTranscriber:
    """Record microphone audio until stopped, then transcribe it locally."""

    def __init__(
        self,
        model_size: str = "base",
        language: Optional[str] = None,
        sample_rate: int = 16_000,
        max_record_seconds: float = 45.0,
    ) -> None:
        self.model_size = model_size
        self.language = language
        self.sample_rate = sample_rate
        self.max_record_seconds = max_record_seconds
        self._model = None
        self._model_lock = threading.Lock()

    def _get_model(self):
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    try:
                        from faster_whisper import WhisperModel
                    except ImportError as exc:
                        raise RuntimeError(
                            "Voice input needs faster-whisper and sounddevice. Install with: "
                            "python -m pip install faster-whisper sounddevice"
                        ) from exc
                    self._model = WhisperModel(
                        self.model_size,
                        device="cpu",
                        compute_type="int8",
                    )
        return self._model

    def record_and_transcribe(
        self,
        stop_event: threading.Event,
        on_listening: Optional[Callable[[], None]] = None,
    ) -> str:
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError(
                "Voice input needs faster-whisper and sounddevice. Install with: "
                "python -m pip install faster-whisper sounddevice"
            ) from exc

        model = self._get_model()
        chunks = []
        callback_errors = []

        def on_audio(indata, _frames, _time_info, status):
            if status:
                callback_errors.append(str(status))
            chunks.append(indata.copy())

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=on_audio,
        ):
            if on_listening:
                on_listening()
            started = time.monotonic()
            while not stop_event.wait(0.1):
                if time.monotonic() - started >= self.max_record_seconds:
                    break

        if not chunks:
            return ""
        audio = np.concatenate(chunks, axis=0).reshape(-1)
        segments, _info = model.transcribe(
            audio,
            language=self.language,
            beam_size=1,
            vad_filter=True,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
