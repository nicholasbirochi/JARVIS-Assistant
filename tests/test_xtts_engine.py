import threading
import time

import pytest

from jarvis import config
from jarvis.voice import xtts_engine


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    # _model/_load_started are module-level singletons by design (the real
    # model must load exactly once per process) -- reset them around every
    # test so tests don't leak state into each other.
    monkeypatch.setattr(xtts_engine, "_model", None)
    monkeypatch.setattr(xtts_engine, "_load_started", False)


def test_has_reference_audio_false_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", tmp_path / "missing.wav")

    assert xtts_engine.has_reference_audio() is False


def test_has_reference_audio_true_when_file_exists(tmp_path, monkeypatch):
    path = tmp_path / "reference.wav"
    path.write_bytes(b"fake wav")
    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", path)

    assert xtts_engine.has_reference_audio() is True


def test_is_ready_false_before_any_load():
    assert xtts_engine.is_ready() is False


def test_is_ready_true_once_model_is_set(monkeypatch):
    monkeypatch.setattr(xtts_engine, "_model", object())

    assert xtts_engine.is_ready() is True


def test_preload_in_background_noop_when_no_reference_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", tmp_path / "missing.wav")
    load_calls = []
    monkeypatch.setattr(xtts_engine, "_load", lambda: load_calls.append(1))

    xtts_engine.preload_in_background()
    time.sleep(0.05)  # give a thread a chance to start, if one wrongly did

    assert load_calls == []
    assert xtts_engine.is_ready() is False


def test_preload_in_background_starts_load_thread_when_reference_exists(tmp_path, monkeypatch):
    path = tmp_path / "reference.wav"
    path.write_bytes(b"fake wav")
    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", path)

    started = threading.Event()
    monkeypatch.setattr(xtts_engine, "_load", lambda: started.set())

    xtts_engine.preload_in_background()
    assert started.wait(timeout=2), "background load never started"


def test_preload_in_background_only_starts_once(tmp_path, monkeypatch):
    path = tmp_path / "reference.wav"
    path.write_bytes(b"fake wav")
    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", path)

    call_count = []
    done = threading.Event()

    def fake_load():
        call_count.append(1)
        done.set()

    monkeypatch.setattr(xtts_engine, "_load", fake_load)

    xtts_engine.preload_in_background()
    assert done.wait(timeout=2)
    xtts_engine.preload_in_background()  # second call -- must not start another thread
    xtts_engine.preload_in_background()

    assert len(call_count) == 1


def test_load_degrades_gracefully_when_model_build_fails(monkeypatch, capsys):
    # e.g. voice-cloning extras not installed, or the download failed --
    # must never crash the background thread silently; is_ready() should
    # just stay False so tts.py keeps using the say-based fallback.
    def _raise():
        raise ModuleNotFoundError("No module named 'TTS'")

    monkeypatch.setattr(xtts_engine, "_build_model", _raise)

    xtts_engine._load()

    assert xtts_engine.is_ready() is False
    assert "falha ao carregar o modelo" in capsys.readouterr().err


def test_synthesize_to_file_raises_when_model_not_loaded():
    with pytest.raises(RuntimeError):
        xtts_engine.synthesize_to_file("olá", "/tmp/out.wav")


def test_synthesize_to_file_delegates_to_loaded_model(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", tmp_path / "reference.wav")
    monkeypatch.setattr(config, "TTS_XTTS_LANGUAGE", "pt")

    calls = []

    class FakeModel:
        def tts_to_file(self, *, text, speaker_wav, language, file_path):
            calls.append((text, speaker_wav, language, file_path))

    monkeypatch.setattr(xtts_engine, "_model", FakeModel())

    xtts_engine.synthesize_to_file("olá", "/tmp/out.wav")

    assert calls == [("olá", str(tmp_path / "reference.wav"), "pt", "/tmp/out.wav")]
