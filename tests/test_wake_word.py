import pytest

from jarvis import config
from jarvis.voice import wake_word


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


class FakeRecorder:
    instances: list["FakeRecorder"] = []

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


def test_listener_wait_blocks_until_engine_detects(monkeypatch):
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine(detect_on_call=2)

    listener = wake_word.WakeWordListener(engine=engine)
    listener.wait()

    recorder = FakeRecorder.instances[-1]
    assert recorder.read_count == 3  # calls 0, 1 miss; call 2 hits
    assert recorder.started is True


def test_listener_close_tears_down_recorder_and_engine(monkeypatch):
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine()

    listener = wake_word.WakeWordListener(engine=engine)
    listener.close()

    recorder = FakeRecorder.instances[-1]
    assert recorder.stopped is True
    assert recorder.deleted is True
    assert engine.closed is True


def test_listener_frame_length_and_sample_rate_proxy_engine(monkeypatch):
    monkeypatch.setattr(wake_word, "PvRecorder", FakeRecorder)
    engine = FakeEngine(frame_length=512, sample_rate=16000)

    listener = wake_word.WakeWordListener(engine=engine)

    assert listener.frame_length == 512
    assert listener.sample_rate == 16000
