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

    def __init__(self, args, poll_sequence, stdin=None):
        self.args = args
        self._poll_sequence = list(poll_sequence)
        self.returncode = None
        self.terminated = False
        self.stdin = stdin  # only the xtts/ffplay path uses this -- say-based tests leave it None

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


def test_speak_shows_original_text_but_speaks_the_prepared_version(monkeypatch):
    # The visualizer transcript should show "IA" exactly as given; the
    # subprocess actually doing the talking should receive "I.A." instead
    # -- see jarvis/voice/speech_text.py. Display and speech must diverge.
    from jarvis.visualizer import state as visualizer_state

    monkeypatch.setattr(tts, "TTS_VOICE", "com.apple.voice.enhanced.pt-BR.Felipe")
    fake_run = FakeRun([0])
    monkeypatch.setattr(subprocess, "run", fake_run)
    published = []
    monkeypatch.setattr(visualizer_state, "publish", lambda state, text="": published.append((state, text)))

    tts.speak("Isso é sobre IA.")

    assert published == [("speaking", "Isso é sobre IA.")]
    assert fake_run.calls == [["say", "-v", "com.apple.voice.enhanced.pt-BR.Felipe", "Isso é sobre I.A."]]


def test_speak_strips_markdown_from_the_displayed_transcript_too(monkeypatch):
    # Real bug reported live: the HUD transcript has no markdown renderer
    # at all (page.html just sets textContent), so a literal "`código`"
    # the model slipped in showed its raw backticks on screen instead of
    # being cleaned up like speech already was.
    from jarvis.visualizer import state as visualizer_state

    monkeypatch.setattr(tts, "TTS_VOICE", "com.apple.voice.enhanced.pt-BR.Felipe")
    monkeypatch.setattr(subprocess, "run", FakeRun([0]))
    published = []
    monkeypatch.setattr(visualizer_state, "publish", lambda state, text="": published.append((state, text)))

    tts.speak("Rode `pytest` antes.")

    assert published == [("speaking", "Rode pytest antes.")]


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


# ---- xtts engine integration (streaming) ----


class FakeStdin:
    """Stand-in for a Popen's .stdin pipe -- collects everything ffplay
    would have been fed, and can simulate ffplay having already died
    (BrokenPipeError on write)."""

    def __init__(self, raise_on_write: Exception | None = None):
        self.written: list[bytes] = []
        self.closed = False
        self._raise_on_write = raise_on_write

    def write(self, data: bytes) -> None:
        if self._raise_on_write:
            raise self._raise_on_write
        self.written.append(data)

    def close(self) -> None:
        self.closed = True


class FakeXttsClient:
    """Stand-in for jarvis.voice.xtts_client -- named _engine here for
    historical reasons, but patches the client module, since that's what
    _speak_via_xtts talks to."""

    def __init__(self, *, has_reference=True, ready=True, chunks=(b"chunk1", b"chunk2"), raises=None):
        self._has_reference = has_reference
        self._ready = ready
        self._chunks = list(chunks)
        self._raises = raises
        self.synthesize_calls: list[str] = []

    def has_reference_audio(self):
        return self._has_reference

    def is_ready(self):
        return self._ready

    def synthesize_stream(self, text):
        self.synthesize_calls.append(text)
        if self._raises:
            raise self._raises
        yield from self._chunks


def _install_fake_xtts_client(monkeypatch, fake_client):
    import jarvis.voice.xtts_client as real_module

    monkeypatch.setattr(real_module, "has_reference_audio", fake_client.has_reference_audio)
    monkeypatch.setattr(real_module, "is_ready", fake_client.is_ready)
    monkeypatch.setattr(real_module, "synthesize_stream", fake_client.synthesize_stream)


def test_speak_uses_xtts_when_engine_configured_and_ready(monkeypatch):
    monkeypatch.setattr(tts, "TTS_ENGINE", "xtts")
    fake_client = FakeXttsClient(chunks=[b"chunk1", b"chunk2"])
    _install_fake_xtts_client(monkeypatch, fake_client)
    popen_calls = []
    fake_stdin = FakeStdin()

    def fake_popen(args, **kwargs):
        popen_calls.append((args, kwargs))
        return FakePopen(args, poll_sequence=[0], stdin=fake_stdin)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    tts.speak("olá")

    assert fake_client.synthesize_calls == ["olá"]
    assert popen_calls[0][0][0] == "ffplay"
    assert popen_calls[0][1]["stdin"] == subprocess.PIPE
    assert fake_stdin.written == [b"chunk1", b"chunk2"]
    assert fake_stdin.closed is True


def test_speak_falls_back_to_say_when_ffplay_itself_fails_to_start(monkeypatch):
    # Real gap this closes: ffplay failing to even launch (not found, no
    # permission, whatever) used to propagate uncaught out of speak()
    # entirely -- total silence, no fallback attempted at all.
    monkeypatch.setattr(tts, "TTS_ENGINE", "xtts")
    _install_fake_xtts_client(monkeypatch, FakeXttsClient(chunks=[b"chunk1"]))

    def raising_popen(*a, **kw):
        raise FileNotFoundError("ffplay not found")

    monkeypatch.setattr(subprocess, "Popen", raising_popen)
    fake_run = FakeRun([0])
    monkeypatch.setattr(subprocess, "run", fake_run)

    tts.speak("olá")  # must not raise

    assert fake_run.calls == [["say", "-v", tts.TTS_VOICE, "olá"]]


def test_speak_falls_back_to_say_when_no_reference_audio_yet(monkeypatch):
    monkeypatch.setattr(tts, "TTS_ENGINE", "xtts")
    _install_fake_xtts_client(monkeypatch, FakeXttsClient(has_reference=False))
    fake_run = FakeRun([0])
    monkeypatch.setattr(subprocess, "run", fake_run)

    tts.speak("olá")

    assert fake_run.calls == [["say", "-v", tts.TTS_VOICE, "olá"]]


def test_speak_falls_back_to_say_when_model_still_loading(monkeypatch):
    monkeypatch.setattr(tts, "TTS_ENGINE", "xtts")
    _install_fake_xtts_client(monkeypatch, FakeXttsClient(ready=False))
    fake_run = FakeRun([0])
    monkeypatch.setattr(subprocess, "run", fake_run)

    tts.speak("olá")

    assert fake_run.calls == [["say", "-v", tts.TTS_VOICE, "olá"]]


def test_speak_falls_back_to_say_when_synthesis_raises_before_any_chunk(monkeypatch):
    monkeypatch.setattr(tts, "TTS_ENGINE", "xtts")
    _install_fake_xtts_client(monkeypatch, FakeXttsClient(raises=RuntimeError("boom")))
    fake_run = FakeRun([0])
    monkeypatch.setattr(subprocess, "run", fake_run)

    tts.speak("olá")

    assert fake_run.calls == [["say", "-v", tts.TTS_VOICE, "olá"]]


def test_speak_treats_empty_stream_as_handled_not_a_failure(monkeypatch):
    # No chunks at all (e.g. empty text) isn't a synthesis failure -- must
    # not fall back to say and speak the text a second time.
    monkeypatch.setattr(tts, "TTS_ENGINE", "xtts")
    _install_fake_xtts_client(monkeypatch, FakeXttsClient(chunks=[]))
    popen_calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: popen_calls.append(1))
    run_calls = []
    monkeypatch.setattr(subprocess, "run", lambda args: run_calls.append(args))

    tts.speak("")

    assert popen_calls == []  # nothing to play, so ffplay never even starts
    assert run_calls == []


def test_speak_does_not_fall_back_to_say_when_xtts_playback_succeeds_with_stop_event(monkeypatch):
    monkeypatch.setattr(tts, "TTS_ENGINE", "xtts")
    _install_fake_xtts_client(monkeypatch, FakeXttsClient())
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **kw: FakePopen(a[0] if a else kw.get("args"), poll_sequence=[0], stdin=FakeStdin())
    )
    say_calls = []
    monkeypatch.setattr(subprocess, "run", lambda args: say_calls.append(args))

    tts.speak("olá", stop_event=threading.Event())

    assert say_calls == []  # never fell through to the say-based path


def test_speak_skips_playback_and_does_not_fall_back_when_interrupted_before_playing(monkeypatch):
    # stop_event already fired by the time the first chunk arrived -- must
    # not start ffplay at all, and must not fall back to say (that would
    # speak the same text out loud right after being told to shut up).
    monkeypatch.setattr(tts, "TTS_ENGINE", "xtts")
    _install_fake_xtts_client(monkeypatch, FakeXttsClient())
    popen_calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: popen_calls.append(1))
    run_calls = []
    monkeypatch.setattr(subprocess, "run", lambda args: run_calls.append(args))

    stop_event = threading.Event()
    stop_event.set()
    tts.speak("olá", stop_event=stop_event)

    assert popen_calls == []
    assert run_calls == []


def test_speak_stops_feeding_ffplay_and_terminates_it_when_interrupted_mid_stream(monkeypatch):
    monkeypatch.setattr(tts, "TTS_ENGINE", "xtts")
    stop_event = threading.Event()

    def chunks_that_interrupt_after_first():
        yield b"chunk1"
        stop_event.set()  # simulate a barge-in landing right after the first chunk played
        yield b"chunk2"  # must never be written -- the loop should stop before this

    fake_client = FakeXttsClient()
    fake_client.synthesize_stream = lambda text: chunks_that_interrupt_after_first()
    _install_fake_xtts_client(monkeypatch, fake_client)

    fake_stdin = FakeStdin()
    fake_process = FakePopen(["ffplay"], poll_sequence=[None], stdin=fake_stdin)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: fake_process)

    tts.speak("uma frase longa", stop_event=stop_event)

    assert fake_stdin.written == [b"chunk1"]
    assert fake_process.terminated is True


def test_speak_stops_writing_when_ffplay_dies_on_its_own(monkeypatch):
    monkeypatch.setattr(tts, "TTS_ENGINE", "xtts")
    _install_fake_xtts_client(monkeypatch, FakeXttsClient(chunks=[b"chunk1", b"chunk2"]))
    fake_stdin = FakeStdin(raise_on_write=BrokenPipeError())
    fake_process = FakePopen(["ffplay"], poll_sequence=[0], stdin=fake_stdin)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: fake_process)
    say_calls = []
    monkeypatch.setattr(subprocess, "run", lambda args: say_calls.append(args))

    tts.speak("olá")  # must not raise

    assert say_calls == []  # a mid-stream failure never falls back to say
