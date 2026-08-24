"""Speech-to-text via local faster-whisper.

The model is lazy-loaded on first call, not at import time -- this is what
keeps the idle-listening state cheap (just the wake-word engine + a mic
stream) until the wake word actually fires. `unload()` drops it again once
a conversation session ends (see conversation.py's run_voice_loop): the
model stays resident for the whole multi-turn session (no per-turn reload
penalty) but doesn't linger in memory once the user's done.
"""

from __future__ import annotations

import gc

import numpy as np

from config import WHISPER_LANGUAGE, WHISPER_MODEL_SIZE

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def unload() -> None:
    """Frees the loaded model; safe to call if nothing is loaded. There's no
    explicit .close() on WhisperModel/ctranslate2, so dropping the only
    reference and forcing a collection is what actually frees the memory now
    instead of "eventually" via deferred GC."""
    global _model
    _model = None
    gc.collect()


def transcribe(pcm16_bytes: bytes) -> str:
    audio = np.frombuffer(pcm16_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    model = _get_model()
    segments, _ = model.transcribe(audio, language=WHISPER_LANGUAGE)
    return " ".join(segment.text.strip() for segment in segments).strip()
