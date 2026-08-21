"""Default wake-word engine: openWakeWord's pretrained "hey_jarvis" model.
No training, no account, no key of any kind -- just a one-time, unauthenticated
download of the ONNX model weights on first use."""

from __future__ import annotations

import numpy as np

FRAME_LENGTH = 1280  # 80ms @ 16kHz, per openWakeWord's documented frame requirement
SAMPLE_RATE = 16000
DEFAULT_THRESHOLD = 0.5
MODEL_NAME = "hey_jarvis"


class OpenWakeWordEngine:
    def __init__(self, threshold: float = DEFAULT_THRESHOLD) -> None:
        from openwakeword import utils
        from openwakeword.model import Model

        utils.download_models([MODEL_NAME])
        self._model = Model(wakeword_models=[MODEL_NAME])
        self._threshold = threshold

    @property
    def frame_length(self) -> int:
        return FRAME_LENGTH

    @property
    def sample_rate(self) -> int:
        return SAMPLE_RATE

    def process(self, frame: list[int]) -> bool:
        scores = self._model.predict(np.array(frame, dtype=np.int16))
        return any(score >= self._threshold for score in scores.values())

    def close(self) -> None:
        pass
