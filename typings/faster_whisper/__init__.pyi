"""Typed subset of faster-whisper's public API used by TaleWeaver (upstream 1.x)."""

from collections.abc import Iterable
from typing import Any

import numpy as np

class Segment:
    text: str

class TranscriptionInfo:
    language: str
    language_probability: float

class WhisperModel:
    def __init__(
        self, model_size_or_path: str, *, device: str = "auto", compute_type: str = "default"
    ) -> None: ...
    def transcribe(
        self, audio: np.ndarray[Any, np.dtype[np.float32]]
    ) -> tuple[Iterable[Segment], TranscriptionInfo]: ...
