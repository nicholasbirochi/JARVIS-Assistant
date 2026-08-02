"""Wake-word detection, engine-agnostic. `pvrecorder` (Picovoice's own
mic-capture library, no account/key required) stays the shared capture layer
regardless of which detection engine (openWakeWord, default; Porcupine,
optional) is active -- only the frame size differs per engine.

Two claps is a second, independent activation trigger that always runs
alongside the primary engine (not a WAKE_WORD_ENGINE choice) -- whichever
fires first wins.
"""

from __future__ import annotations

import threading
from typing import Callable, Literal

from pvrecorder import PvRecorder

from jarvis.voice.engines.base import WakeWordEngine
from jarvis.voice.engines.clap_detector import ClapDetector

Trigger = Literal["wake_word", "clap"]

_ENGINE_FACTORIES: dict[str, Callable[[], WakeWordEngine]] = {}


def _openwakeword_factory() -> WakeWordEngine:
    from jarvis.voice.engines.openwakeword_engine import OpenWakeWordEngine

    return OpenWakeWordEngine()


def _porcupine_factory() -> WakeWordEngine:
    from jarvis.voice.engines.porcupine_engine import PorcupineEngine

    return PorcupineEngine()


_ENGINE_FACTORIES["openwakeword"] = _openwakeword_factory
_ENGINE_FACTORIES["porcupine"] = _porcupine_factory


def get_wake_word_engine() -> WakeWordEngine:
    from jarvis.config import WAKE_WORD_ENGINE  # live lookup -- monkeypatchable in tests

    try:
        factory = _ENGINE_FACTORIES[WAKE_WORD_ENGINE]
    except KeyError:
        raise ValueError(f"WAKE_WORD_ENGINE desconhecido: {WAKE_WORD_ENGINE!r}") from None
    return factory()


class WakeWordListener:
    """Holds the mic stream open and blocks until the wake word is heard.

    Kept open across calls to `wait()` so idle listening only costs the
    detection engine + an open mic stream -- no heavier model is loaded
    until a caller explicitly starts recording an utterance on the same
    stream.
    """

    def __init__(
        self,
        engine: WakeWordEngine | None = None,
        clap_detector: ClapDetector | None = None,
    ) -> None:
        self._engine = engine or get_wake_word_engine()
        self._recorder = PvRecorder(device_index=-1, frame_length=self._engine.frame_length)
        self._recorder.start()
        self._clap_detector = clap_detector if clap_detector is not None else self._maybe_clap_detector()
        self._frame_seconds = self._engine.frame_length / self._engine.sample_rate

    @staticmethod
    def _maybe_clap_detector() -> ClapDetector | None:
        from jarvis.config import CLAP_ACTIVATION_ENABLED

        return ClapDetector() if CLAP_ACTIVATION_ENABLED else None

    @property
    def frame_length(self) -> int:
        return self._engine.frame_length

    @property
    def sample_rate(self) -> int:
        return self._engine.sample_rate

    def read_frame(self) -> list[int]:
        return self._recorder.read()

    def wait(self, stop_event: threading.Event | None = None) -> Trigger | None:
        """Blocks until the wake word is heard, two claps land within the
        configured window, or `stop_event` is set -- whichever comes first.
        Returns which trigger it was, or None if stopped externally (the
        menu-bar app's off button sets stop_event to make this return
        promptly instead of blocking forever)."""
        while True:
            if stop_event is not None and stop_event.is_set():
                return None
            frame = self._recorder.read()
            if self._engine.process(frame):
                return "wake_word"
            if self._clap_detector is not None and self._clap_detector.process(frame, self._frame_seconds):
                return "clap"

    def close(self) -> None:
        self._recorder.stop()
        self._recorder.delete()
        self._engine.close()
