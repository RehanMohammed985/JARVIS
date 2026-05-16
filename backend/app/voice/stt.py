from __future__ import annotations

import io
import wave
from pathlib import Path

import numpy as np

from app.config import settings


class SpeechToText:
    def __init__(self) -> None:
        self._model = None

    def _ensure(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        device = settings.whisper_device
        if device == "auto":
            try:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                device = "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        self._model = WhisperModel(
            settings.whisper_model_size,
            device=device,
            compute_type=compute_type,
        )

    def transcribe_pcm16_mono(self, pcm: bytes, sample_rate: int = 16000) -> str:
        self._ensure()
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        try:
            segments, _info = self._model.transcribe(
                audio,
                language="en",
                vad_filter=True,
                beam_size=1,
                condition_on_previous_text=False,
                without_timestamps=True,
            )
        except Exception:
            segments, _info = self._model.transcribe(
                audio,
                language="en",
                vad_filter=True,
                beam_size=1,
            )
        parts: list[str] = []
        for s in segments:
            parts.append(s.text.strip())
        return " ".join(parts).strip()


_stt: SpeechToText | None = None


def get_stt() -> SpeechToText:
    global _stt
    if _stt is None:
        _stt = SpeechToText()
    return _stt


def pcm_to_wav_bytes(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()
