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

from voice.engines.base import WakeWordEngine
from voice.engines.clap_detector import ClapDetector

Trigger = Literal["wake_word", "clap"]

_ENGINE_FACTORIES: dict[str, Callable[[], WakeWordEngine]] = {}


def _openwakeword_factory() -> WakeWordEngine:
    from voice.engines.openwakeword_engine import OpenWakeWordEngine

    return OpenWakeWordEngine()


def _porcupine_factory() -> WakeWordEngine:
    from voice.engines.porcupine_engine import PorcupineEngine

    return PorcupineEngine()


_ENGINE_FACTORIES["openwakeword"] = _openwakeword_factory
_ENGINE_FACTORIES["porcupine"] = _porcupine_factory


def get_wake_word_engine() -> WakeWordEngine:
    from config import WAKE_WORD_ENGINE  # live lookup -- monkeypatchable in tests

    try:
        factory = _ENGINE_FACTORIES[WAKE_WORD_ENGINE]
    except KeyError:
        raise ValueError(f"WAKE_WORD_ENGINE desconhecido: {WAKE_WORD_ENGINE!r}") from None
    return factory()


def _select_device_index() -> int:
    """Picks which input device PvRecorder should open. Deliberately not
    always -1 ("the system's current default") -- see
    config.PREFERRED_MIC_NAME_SUBSTRING's comment for the real, confirmed
    failure this guards against (a Bluetooth accessory silently becoming
    the default input, with JARVIS listening through it instead of the
    laptop with zero errors anywhere). Falls back to -1 if no device name
    matches, so this still works on a different machine or if the
    built-in mic is ever genuinely unavailable."""
    from config import PREFERRED_MIC_NAME_SUBSTRING  # live lookup -- monkeypatchable in tests

    try:
        devices = PvRecorder.get_available_devices()
    except Exception:
        return -1  # can't enumerate devices for some reason -- fall back rather than fail construction
    for index, name in enumerate(devices):
        if PREFERRED_MIC_NAME_SUBSTRING in name:
            return index
    return -1


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
        self._recorder = self._open_recorder()
        self._clap_detector = clap_detector if clap_detector is not None else self._maybe_clap_detector()
        self._frame_seconds = self._engine.frame_length / self._engine.sample_rate

    def _open_recorder(self) -> PvRecorder:
        recorder = PvRecorder(device_index=_select_device_index(), frame_length=self._engine.frame_length)
        recorder.start()
        return recorder

    @staticmethod
    def _maybe_clap_detector() -> ClapDetector | None:
        from config import CLAP_ACTIVATION_ENABLED

        return ClapDetector() if CLAP_ACTIVATION_ENABLED else None

    @property
    def frame_length(self) -> int:
        return self._engine.frame_length

    @property
    def sample_rate(self) -> int:
        return self._engine.sample_rate

    def read_frame(self) -> list[int]:
        return self._recorder.read()

    def check_trigger(self, frame: list[int], *, include_clap: bool = True) -> Trigger | None:
        """Runs one already-read frame through the wake-word engine + clap
        detector -- the same checks `wait()`'s loop body does, exposed
        separately so a caller can read frames on its own schedule instead
        of blocking inside wait().

        include_clap=False skips the clap detector entirely, checking only
        the neural wake-word engine. Used by conversation.py's barge-in
        watcher (while JARVIS is speaking): the clap detector is plain
        peak-amplitude detection (see clap_detector.py's module docstring),
        not real voice recognition -- any sufficiently loud, sharp noise
        (a dropped object, a door) would false-positive as two claps and
        cut JARVIS off mid-sentence for no real reason. Initial activation
        from idle (wait(), below) still checks both -- clap-to-activate is
        a deliberate, real feature there, just not a safe barge-in signal
        while JARVIS is already actively engaged and talking."""
        if self._engine.process(frame):
            return "wake_word"
        if include_clap and self._clap_detector is not None and self._clap_detector.process(frame, self._frame_seconds):
            return "clap"
        return None

    def wait(
        self,
        stop_event: threading.Event | None = None,
        wake_event: threading.Event | None = None,
    ) -> Trigger | None:
        """Blocks until the wake word is heard, two claps land within the
        configured window, or `stop_event` is set -- whichever comes first.
        Returns which trigger it was, or None if stopped externally (the
        menu-bar app's off button sets stop_event to make this return
        promptly instead of blocking forever).

        `wake_event`, if given, is checked on the same cycle: when set, the
        underlying mic stream is torn down and reopened (see
        _reset_recorder), then waiting continues transparently -- no
        return, the caller never even notices beyond a brief gap. This is
        real, confirmed behavior, not speculative: a live session ran for
        hours, the machine went through an actual macOS Clamshell Sleep,
        and wake-word detection silently stopped firing afterward with no
        exception anywhere -- consistent with a stream that's still
        technically open but has quietly stopped delivering real frames.
        menubar.py sets this from a real NSWorkspace wake
        notification."""
        while True:
            if stop_event is not None and stop_event.is_set():
                return None
            if wake_event is not None and wake_event.is_set():
                self._reset_recorder()
                wake_event.clear()
            frame = self._recorder.read()
            trigger = self.check_trigger(frame)
            if trigger is not None:
                return trigger

    def _reset_recorder(self) -> None:
        try:
            self._recorder.stop()
            self._recorder.delete()
        except Exception:
            pass  # best-effort teardown of a stream that may already be in a bad state
        self._recorder = self._open_recorder()

    def close(self) -> None:
        self._recorder.stop()
        self._recorder.delete()
        self._engine.close()
