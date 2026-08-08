import subprocess
import threading

import pytest

from jarvis.voice import tts


@pytest.fixture(autouse=True)
def _default_to_say_engine(monkeypatch):
    # Isolates every test below from the real TTS_ENGINE default ("xtts")
    # and the real xtts_engine/filesystem state -- tests that specifically
    # exercise the xtts path override this explicitly.
    monkeypatch.setattr(tts, "TTS_ENGINE", "say")


class FakeCompletedProcess:
    def __init__(self, returncode):
        self.returncode = returncode


class FakeRun:
    """Stand-in for subprocess.run, used for the no-stop_event path."""

    def __init__(self, returncodes):
        self._returncodes = list(returncodes)
        self.calls: list[list[str]] = []

    def __call__(self, args):
        self.calls.append(args)
        return FakeCompletedProcess(self._returncodes.pop(0))


class FakePopen:
    """Stand-in for subprocess.Popen. `poll_sequence` models one poll()
    result per call -- None means "still running", an int means finished
    with that returncode. Used for the stop_event path."""

    def __init__(self, args, poll_sequence):
        self.args = args
        self._poll_sequence = list(poll_sequence)
        self.returncode = None
        self.terminated = False

    def poll(self):
        if self._poll_sequence:
            value = self._poll_sequence.pop(0)
            if value is not None:
                self.returncode = value
            return value
        return self.returncode

    def terminate(self):
        self.terminated = True

    def wait(self):
        if self.returncode is None:
            self.returncode = -15  # SIGTERM, as if terminate() just killed it
        return self.returncode


def test_speak_without_stop_event_uses_plain_run(monkeypatch):
    monkeypatch.setattr(tts, "TTS_VOICE", "com.apple.voice.enhanced.pt-BR.Felipe")
    fake_run = FakeRun([0])
    monkeypatch.setattr(subprocess, "run", fake_run)

    tts.speak("olá")

    assert fake_run.calls == [["say", "-v", "com.apple.voice.enhanced.pt-BR.Felipe", "olá"]]


def test_speak_falls_back_when_configured_voice_is_unavailable(monkeypatch):
    monkeypatch.setattr(tts, "TTS_VOICE", "com.apple.voice.enhanced.pt-BR.Felipe")
    fake_run = FakeRun([1, 0])  # primary voice fails, fallback succeeds
    monkeypatch.setattr(subprocess, "run", fake_run)

    tts.speak("olá")

    assert fake_run.calls == [
        ["say", "-v", "com.apple.voice.enhanced.pt-BR.Felipe", "olá"],
        ["say", "-v", tts.FALLBACK_VOICE, "olá"],
    ]


def test_speak_raises_when_even_the_fallback_voice_fails(monkeypatch):
    monkeypatch.setattr(tts, "TTS_VOICE", tts.FALLBACK_VOICE)
    monkeypatch.setattr(subprocess, "run", FakeRun([1]))

    with pytest.raises(RuntimeError):
        tts.speak("olá")


def test_speak_with_stop_event_lets_normal_speech_finish(monkeypatch):
    monkeypatch.setattr(tts, "TTS_VOICE", "com.apple.voice.enhanced.pt-BR.Felipe")
    monkeypatch.setattr(subprocess, "Popen", lambda args: FakePopen(args, poll_sequence=[0]))

    tts.speak("olá", stop_event=threading.Event())  # never set -- finishes normally


def test_speak_interrupts_immediately_when_stop_event_fires_mid_sentence(monkeypatch):
    monkeypatch.setattr(tts, "TTS_VOICE", "com.apple.voice.enhanced.pt-BR.Felipe")
    monkeypatch.setattr(tts.time, "sleep", lambda _: None)

    stop_event = threading.Event()
    created: list[FakePopen] = []

    def fake_popen(args):
        # Still "running" the first couple of polls, then the interrupt
        # fires -- simulates the process being mid-sentence when muted.
        proc = FakePopen(args, poll_sequence=[None, None])
        created.append(proc)
        return proc

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    poll_count = 0
    original_is_set = stop_event.is_set

    def is_set_after_two_polls():
        nonlocal poll_count
        poll_count += 1
        return poll_count > 2

    monkeypatch.setattr(stop_event, "is_set", is_set_after_two_polls)

    tts.speak("uma frase bem longa", stop_event=stop_event)

    assert created[0].terminated is True


def test_speak_does_not_fall_back_when_interrupted_on_purpose(monkeypatch):
    # Being killed by stop_event isn't a real failure -- must not trigger
    # the fallback-voice retry.
    monkeypatch.setattr(tts, "TTS_VOICE", "com.apple.voice.enhanced.pt-BR.Felipe")
    monkeypatch.setattr(tts.time, "sleep", lambda _: None)

    stop_event = threading.Event()
    stop_event.set()  # already muted before speech even starts polling
    popen_calls = []
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda args: popen_calls.append(args) or FakePopen(args, poll_sequence=[None]),
    )

    tts.speak("olá", stop_event=stop_event)

    assert len(popen_calls) == 1  # only the primary voice was ever started


# ---- xtts engine integration ----


class FakeXttsEngine:
    """Stand-in for jarvis.voice.xtts_client (tts.py's actual dependency --
    named _engine here for historical reasons, but patches the client
    module, since that's what _speak_via_xtts talks to now)."""

    def __init__(self, *, has_reference=True, ready=True, raises=None):
        self._has_reference = has_reference
        self._ready = ready
        self._raises = raises
        self.synthesize_calls: list[tuple[str, str]] = []

    def has_reference_audio(self):
        return self._has_reference

    def is_ready(self):
        return self._ready

    def synthesize_to_file(self, text, out_path):
        self.synthesize_calls.append((text, out_path))
        if self._raises:
            raise self._raises
        # Write something real -- speak() unlinks this path afterward.
        with open(out_path, "wb") as f:
            f.write(b"RIFF....WAVEfake")


def _install_fake_xtts_engine(monkeypatch, fake_engine):
    import jarvis.voice.xtts_client as real_module

    monkeypatch.setattr(real_module, "has_reference_audio", fake_engine.has_reference_audio)
    monkeypatch.setattr(real_module, "is_ready", fake_engine.is_ready)
    monkeypatch.setattr(real_module, "synthesize_to_file", fake_engine.synthesize_to_file)


def test_speak_uses_xtts_when_engine_configured_and_ready(monkeypatch):
    monkeypatch.setattr(tts, "TTS_ENGINE", "xtts")
    fake_engine = FakeXttsEngine()
    _install_fake_xtts_engine(monkeypatch, fake_engine)
    monkeypatch.setattr(subprocess, "run", FakeRun([0]))  # afplay

    tts.speak("olá")

    assert fake_engine.synthesize_calls[0][0] == "olá"


def test_speak_falls_back_to_say_when_no_reference_audio_yet(monkeypatch):
    monkeypatch.setattr(tts, "TTS_ENGINE", "xtts")
    _install_fake_xtts_engine(monkeypatch, FakeXttsEngine(has_reference=False))
    fake_run = FakeRun([0])
    monkeypatch.setattr(subprocess, "run", fake_run)

    tts.speak("olá")

    assert fake_run.calls == [["say", "-v", tts.TTS_VOICE, "olá"]]


def test_speak_falls_back_to_say_when_model_still_loading(monkeypatch):
    monkeypatch.setattr(tts, "TTS_ENGINE", "xtts")
    _install_fake_xtts_engine(monkeypatch, FakeXttsEngine(ready=False))
    fake_run = FakeRun([0])
    monkeypatch.setattr(subprocess, "run", fake_run)

    tts.speak("olá")

    assert fake_run.calls == [["say", "-v", tts.TTS_VOICE, "olá"]]


def test_speak_falls_back_to_say_when_synthesis_raises(monkeypatch):
    monkeypatch.setattr(tts, "TTS_ENGINE", "xtts")
    _install_fake_xtts_engine(monkeypatch, FakeXttsEngine(raises=RuntimeError("boom")))
    fake_run = FakeRun([0])
    monkeypatch.setattr(subprocess, "run", fake_run)

    tts.speak("olá")

    assert fake_run.calls == [["say", "-v", tts.TTS_VOICE, "olá"]]


def test_speak_does_not_fall_back_to_say_when_xtts_playback_succeeds_with_stop_event(monkeypatch):
    monkeypatch.setattr(tts, "TTS_ENGINE", "xtts")
    _install_fake_xtts_engine(monkeypatch, FakeXttsEngine())
    monkeypatch.setattr(subprocess, "Popen", lambda args: FakePopen(args, poll_sequence=[0]))
    say_calls = []
    monkeypatch.setattr(subprocess, "run", lambda args: say_calls.append(args))

    tts.speak("olá", stop_event=threading.Event())

    assert say_calls == []  # never fell through to the say-based path


def test_speak_skips_playback_and_does_not_fall_back_when_interrupted_before_playing(monkeypatch):
    # stop_event already fired by the time (slow) generation finished --
    # must not play stale audio, and must not fall back to say (that would
    # speak the same text out loud right after being told to shut up).
    monkeypatch.setattr(tts, "TTS_ENGINE", "xtts")
    _install_fake_xtts_engine(monkeypatch, FakeXttsEngine())
    popen_calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda args: popen_calls.append(args))
    run_calls = []
    monkeypatch.setattr(subprocess, "run", lambda args: run_calls.append(args))

    stop_event = threading.Event()
    stop_event.set()
    tts.speak("olá", stop_event=stop_event)

    assert popen_calls == []
    assert run_calls == []
