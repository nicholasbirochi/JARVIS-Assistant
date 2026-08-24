"""Optional adapter -- kept for anyone who wants Porcupine's custom
wake-word training tools. Requires a free Picovoice AccessKey, unlike the
default openWakeWord engine."""

from __future__ import annotations

import pvporcupine

from config import PICOVOICE_ACCESS_KEY, WAKE_WORD


class PorcupineEngine:
    def __init__(self) -> None:
        if not PICOVOICE_ACCESS_KEY:
            raise RuntimeError(
                "PICOVOICE_ACCESS_KEY não configurada. Preencha o arquivo .env, "
                "ou use WAKE_WORD_ENGINE=openwakeword (padrão, sem chave)."
            )
        self._porcupine = pvporcupine.create(access_key=PICOVOICE_ACCESS_KEY, keywords=[WAKE_WORD])

    @property
    def frame_length(self) -> int:
        return self._porcupine.frame_length

    @property
    def sample_rate(self) -> int:
        return self._porcupine.sample_rate

    def process(self, frame: list[int]) -> bool:
        return self._porcupine.process(frame) >= 0

    def close(self) -> None:
        self._porcupine.delete()
