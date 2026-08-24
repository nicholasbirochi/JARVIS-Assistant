import pytest

import config
from voice import wake_word


class FakeEngine:
    def __init__(self, frame_length=1280, sample_rate=16000, detect_on_call=None):
        self.frame_length = frame_length
        self.sample_rate = sample_rate
        self._detect_on_call = detect_on_call  # 0-indexed call number that returns True
        self._calls = 0
        self.closed = False

    def process(self, frame) -> bool:
        result = self._calls == self._detect_on_call
        self._calls += 1
        return result

    def close(self) -> None:
        self.closed = True


class FakeClapDetector:
    def __init__(self, detect_on_call=None):
        self._detect_on_call = detect_on_call  # 0-indexed call number that returns True
        self._calls = 0

    def process(self, frame, frame_seconds) -> bool:
        result = self._calls == self._detect_on_call
        self._calls += 1
        return result


class FakeRecorder:
    instances: list["FakeRecorder"] = []
    available_devices: list[str] = []

    @classmethod
    def get_available_devices(cls):
        return cls.available_devices

    def __init__(self, device_index, frame_length):
        self.device_index = device_index
        self.frame_length = frame_length
        self.started = False
        self.stopped = False
        self.deleted = False
        self.read_count = 0
        FakeRecorder.instances.append(self)

    def start(self) -> None:
        self.started = True

    def read(self):
        self.read_count += 1
        return [0] * self.frame_length

    def stop(self) -> None:
        self.stopped = True

    def delete(self) -> None:
        self.deleted = True


def test_get_wake_word_engine_dispatches_by_config(monkeypatch):
    fake_factory_calls = []
    monkeypatch.setitem(wake_word._ENGINE_FACTORIES, "fake", lambda: fake_factory_calls.append(1) or FakeEngine())
    monkeypatch.setattr(config, "WAKE_WORD_ENGINE", "fake")

    engine = wake_word.get_wake_word_engine()

    assert isinstance(engine, FakeEngine)
    assert fake_factory_calls == [1]


def test_get_wake_word_engine_unknown_raises(monkeypatch):
    monkeypatch.setattr(config, "WAKE_WORD_ENGINE", "not-a-real-engine")
    with pytest.raises(ValueError):
        wake_word.get_wake_word_engine()


# ---- _select_device_index -- see config.PREFERRED_MIC_NAME_SUBSTRING's
# comment for the real, confirmed bug this guards against: a Bluetooth
# accessory (an Apple Watch) silently became the system default input
# device, and JARVIS listened through it instead of the laptop's mic. ----


def test_select_device_index_prefers_device_matching_configured_substring(monkeypatch):
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    monkeypatch.setattr(
        FakeRecorder, "available_devices", ["Smart Watch de Nicholas", "Microfone (MacBook Air)", "iPhone Microphone"]
    )
    monkeypatch.setattr(config, "PREFERRED_MIC_NAME_SUBSTRING", "MacBook")

    assert wake_word._select_device_index() == 1


def test_select_device_index_falls_back_to_system_default_when_no_match(monkeypatch):
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    monkeypatch.setattr(FakeRecorder, "available_devices", ["Smart Watch de Nicholas", "iPhone Microphone"])
    monkeypatch.setattr(config, "PREFERRED_MIC_NAME_SUBSTRING", "MacBook")

    assert wake_word._select_device_index() == -1


def test_select_device_index_falls_back_when_enumeration_raises(monkeypatch):
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)

    def raising_get_available_devices():
        raise OSError("no audio subsystem")

    monkeypatch.setattr(FakeRecorder, "get_available_devices", staticmethod(raising_get_available_devices))

    assert wake_word._select_device_index() == -1


def test_listener_construction_uses_the_selected_device_index(monkeypatch):
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    monkeypatch.setattr(FakeRecorder, "available_devices", ["Smart Watch de Nicholas", "Microfone (MacBook Air)"])
    monkeypatch.setattr(config, "PREFERRED_MIC_NAME_SUBSTRING", "MacBook")
    engine = FakeEngine()

    wake_word.WakeWordListener(engine=engine, clap_detector=FakeClapDetector())

    assert FakeRecorder.instances[-1].device_index == 1


def test_listener_wait_returns_wake_word_when_engine_detects(monkeypatch):
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine(detect_on_call=2)

    listener = wake_word.WakeWordListener(engine=engine, clap_detector=FakeClapDetector())
    trigger = listener.wait()

    recorder = FakeRecorder.instances[-1]
    assert trigger == "wake_word"
    assert recorder.read_count == 3  # calls 0, 1 miss; call 2 hits


def test_listener_wait_returns_clap_when_clap_detector_fires_first(monkeypatch):
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine(detect_on_call=None)  # never fires
    clap_detector = FakeClapDetector(detect_on_call=1)

    listener = wake_word.WakeWordListener(engine=engine, clap_detector=clap_detector)
    trigger = listener.wait()

    assert trigger == "clap"


def test_listener_wait_returns_none_when_stop_event_already_set(monkeypatch):
    import threading

    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine(detect_on_call=None)  # never fires
    stop_event = threading.Event()
    stop_event.set()

    listener = wake_word.WakeWordListener(engine=engine, clap_detector=FakeClapDetector())
    trigger = listener.wait(stop_event=stop_event)

    recorder = FakeRecorder.instances[-1]
    assert trigger is None
    assert recorder.read_count == 0  # returned before ever reading a frame


def test_listener_wait_stops_mid_wait_once_event_is_set(monkeypatch):
    import threading

    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine(detect_on_call=None)  # never fires
    stop_event = threading.Event()

    class StoppingClapDetector(FakeClapDetector):
        """Sets stop_event partway through, simulating the menu-bar app's
        off button being clicked while wait() is already blocking."""

        def process(self, frame, frame_seconds) -> bool:
            if self._calls == 2:
                stop_event.set()
            return super().process(frame, frame_seconds)

    listener = wake_word.WakeWordListener(engine=engine, clap_detector=StoppingClapDetector())
    trigger = listener.wait(stop_event=stop_event)

    assert trigger is None


def test_reset_recorder_tears_down_old_and_creates_a_new_one(monkeypatch):
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine()
    listener = wake_word.WakeWordListener(engine=engine, clap_detector=FakeClapDetector())
    old_recorder = FakeRecorder.instances[-1]

    listener._reset_recorder()

    assert old_recorder.stopped is True
    assert old_recorder.deleted is True
    new_recorder = FakeRecorder.instances[-1]
    assert new_recorder is not old_recorder
    assert new_recorder.started is True


def test_wait_resets_recorder_when_wake_event_is_set_then_clears_it(monkeypatch):
    # Real, confirmed failure mode: a machine wake from sleep left the mic
    # stream silently dead (no exception, just no real frames anymore).
    # menubar.py sets wake_event from an actual NSWorkspace wake
    # notification -- this is the recovery path for that.
    import threading

    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine(detect_on_call=0)  # fires on the first read after the reset
    wake_event = threading.Event()
    wake_event.set()

    listener = wake_word.WakeWordListener(engine=engine, clap_detector=FakeClapDetector())
    old_recorder = FakeRecorder.instances[-1]

    trigger = listener.wait(wake_event=wake_event)

    assert trigger == "wake_word"
    assert old_recorder.stopped is True  # torn down because wake_event was set
    assert wake_event.is_set() is False  # cleared once handled


def test_wait_ignores_wake_event_when_not_set(monkeypatch):
    import threading

    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine(detect_on_call=0)
    wake_event = threading.Event()  # never set

    listener = wake_word.WakeWordListener(engine=engine, clap_detector=FakeClapDetector())
    old_recorder = FakeRecorder.instances[-1]

    trigger = listener.wait(wake_event=wake_event)

    assert trigger == "wake_word"
    assert old_recorder.stopped is False  # never reset -- wake_event was never set


def test_listener_close_tears_down_recorder_and_engine(monkeypatch):
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine()

    listener = wake_word.WakeWordListener(engine=engine, clap_detector=FakeClapDetector())
    listener.close()

    recorder = FakeRecorder.instances[-1]
    assert recorder.stopped is True
    assert recorder.deleted is True
    assert engine.closed is True


def test_listener_frame_length_and_sample_rate_proxy_engine(monkeypatch):
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine(frame_length=512, sample_rate=16000)

    listener = wake_word.WakeWordListener(engine=engine, clap_detector=FakeClapDetector())

    assert listener.frame_length == 512
    assert listener.sample_rate == 16000


def test_check_trigger_returns_wake_word_without_reading_a_frame_itself(monkeypatch):
    # check_trigger takes an already-read frame -- unlike wait(), it must
    # never call the recorder itself, since conversation.py's barge-in
    # watcher reads frames on its own schedule while speak() is playing.
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine(detect_on_call=0)

    listener = wake_word.WakeWordListener(engine=engine, clap_detector=FakeClapDetector())
    recorder = FakeRecorder.instances[-1]
    read_count_before = recorder.read_count

    trigger = listener.check_trigger([0] * 1280)

    assert trigger == "wake_word"
    assert recorder.read_count == read_count_before


def test_check_trigger_returns_clap(monkeypatch):
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine(detect_on_call=None)
    clap_detector = FakeClapDetector(detect_on_call=0)

    listener = wake_word.WakeWordListener(engine=engine, clap_detector=clap_detector)

    assert listener.check_trigger([0] * 1280) == "clap"


def test_check_trigger_returns_none_when_nothing_fires(monkeypatch):
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine(detect_on_call=None)

    listener = wake_word.WakeWordListener(engine=engine, clap_detector=FakeClapDetector())

    assert listener.check_trigger([0] * 1280) is None


def test_check_trigger_include_clap_false_suppresses_a_real_clap(monkeypatch):
    # Real complaint this fixes: clap detection is plain peak-amplitude
    # noise detection, not real voice recognition -- conversation.py's
    # barge-in watcher passes include_clap=False specifically so a random
    # loud sound can't interrupt JARVIS mid-sentence.
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine(detect_on_call=None)
    clap_detector = FakeClapDetector(detect_on_call=0)

    listener = wake_word.WakeWordListener(engine=engine, clap_detector=clap_detector)

    assert listener.check_trigger([0] * 1280, include_clap=False) is None


def test_check_trigger_include_clap_false_still_returns_wake_word(monkeypatch):
    # The exclusion is specific to the clap detector -- real voice
    # recognition must still interrupt regardless of include_clap.
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine(detect_on_call=0)

    listener = wake_word.WakeWordListener(engine=engine, clap_detector=FakeClapDetector())

    assert listener.check_trigger([0] * 1280, include_clap=False) == "wake_word"


def test_listener_disables_clap_detector_when_config_flag_off(monkeypatch):
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    monkeypatch.setattr(config, "CLAP_ACTIVATION_ENABLED", False)
    engine = FakeEngine()

    listener = wake_word.WakeWordListener(engine=engine)

    assert listener._clap_detector is None


def test_listener_enables_real_clap_detector_by_default(monkeypatch):
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    monkeypatch.setattr(config, "CLAP_ACTIVATION_ENABLED", True)
    engine = FakeEngine()

    listener = wake_word.WakeWordListener(engine=engine)

    assert listener._clap_detector is not None
