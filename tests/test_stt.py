import faster_whisper

from jarvis.voice import stt


class FakeWhisperModel:
    instances = 0

    def __init__(self, model_size, device, compute_type):
        FakeWhisperModel.instances += 1
        self.model_size = model_size

    def transcribe(self, audio, language):
        return [type("Segment", (), {"text": " oi jarvis "})()], None


def test_get_model_is_a_cached_singleton(monkeypatch):
    monkeypatch.setattr(stt, "_model", None)
    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisperModel)
    FakeWhisperModel.instances = 0

    first = stt._get_model()
    second = stt._get_model()

    assert first is second
    assert FakeWhisperModel.instances == 1


def test_unload_resets_singleton_and_reloads_on_next_call(monkeypatch):
    monkeypatch.setattr(stt, "_model", None)
    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisperModel)
    FakeWhisperModel.instances = 0

    stt._get_model()
    stt.unload()
    assert stt._model is None

    stt._get_model()
    assert FakeWhisperModel.instances == 2  # reloaded after unload


def test_transcribe_uses_model_and_joins_segments(monkeypatch):
    monkeypatch.setattr(stt, "_model", None)
    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisperModel)

    result = stt.transcribe(b"\x00\x00" * 100)

    assert result == "oi jarvis"
