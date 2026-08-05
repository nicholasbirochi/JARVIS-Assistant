import subprocess
import threading

import pytest

from jarvis.voice import tts


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
