import threading

import pytest

from jarvis.assistant import conversation
from jarvis.assistant import llm_client
from jarvis.assistant.providers import ProviderResponse
from jarvis.config import CLAP_GREETING, GREETING


def test_greeting_by_trigger_maps_wake_word_and_clap():
    assert conversation._GREETING_BY_TRIGGER["wake_word"] == GREETING
    assert conversation._GREETING_BY_TRIGGER["clap"] == CLAP_GREETING


class ScriptedProvider:
    def __init__(self, responses):
        self._responses = list(responses)

    def chat(self, messages, tool_specs):
        return self._responses.pop(0)


class FakeListener:
    """Used where the test doesn't care about barge-in at all -- just
    needs to exist as a valid listener so _speak_with_barge_in's watcher
    thread has something safe to call without raising."""

    def read_frame(self):
        return [0]

    def check_trigger(self, frame):
        return None


def _install_scripted_provider(monkeypatch, responses):
    monkeypatch.setattr(llm_client, "_provider", ScriptedProvider(responses))


class _ScriptedTriggerListener:
    """check_trigger() returns from `triggers` in order (None once
    exhausted, i.e. never fires again) -- read_frame() itself is a no-op,
    just something for the watcher thread to call."""

    def __init__(self, triggers):
        self._triggers = list(triggers)
        self.read_frame_calls = 0

    def read_frame(self):
        self.read_frame_calls += 1
        return [0]

    def check_trigger(self, frame):
        return self._triggers.pop(0) if self._triggers else None


def test_speak_with_barge_in_returns_none_when_speech_finishes_uninterrupted():
    listener = _ScriptedTriggerListener(triggers=[])  # never fires

    def instant_speak(text, stop_event=None):
        pass  # "speech" finishes on its own, watcher never gets to fire

    result = conversation._speak_with_barge_in(instant_speak, "oi", listener)

    assert result is None


def test_speak_with_barge_in_interrupts_speech_and_returns_wake_word():
    listener = _ScriptedTriggerListener(triggers=["wake_word"])

    def blocking_speak(text, stop_event):
        # Stands in for tts.speak()'s real behavior: keeps "talking" until
        # told to stop.
        stop_event.wait(timeout=2)

    result = conversation._speak_with_barge_in(blocking_speak, "uma frase longa", listener)

    assert result == "wake_word"


def test_speak_with_barge_in_interrupts_speech_and_returns_clap():
    listener = _ScriptedTriggerListener(triggers=["clap"])

    def blocking_speak(text, stop_event):
        stop_event.wait(timeout=2)

    result = conversation._speak_with_barge_in(blocking_speak, "uma frase longa", listener)

    assert result == "clap"


def test_speak_with_barge_in_stops_watching_once_speech_ends_on_its_own():
    # Nothing ever barges in -- the watcher must still stop promptly
    # (rather than spin forever) once speak() returns.
    listener = _ScriptedTriggerListener(triggers=[])

    def instant_speak(text, stop_event=None):
        pass

    conversation._speak_with_barge_in(instant_speak, "oi", listener)

    # If the watcher were still running, read_frame_calls would keep
    # climbing -- give it a moment and confirm it settled instead.
    import time

    calls_after = listener.read_frame_calls
    time.sleep(0.05)
    assert listener.read_frame_calls == calls_after


def test_speak_with_barge_in_propagates_the_outer_stop_event():
    # "Desligar JARVIS" firing mid-speech must still cut speech short via
    # the same mechanism -- the watcher notices the outer stop_event too,
    # not just its own wake-word/clap checks.
    listener = _ScriptedTriggerListener(triggers=[])  # no real barge-in trigger
    outer_stop_event = threading.Event()

    def speak_then_get_stopped(text, stop_event):
        outer_stop_event.set()  # simulate the off-toggle firing while "talking"
        stop_event.wait(timeout=2)

    result = conversation._speak_with_barge_in(
        speak_then_get_stopped, "frase", listener, stop_event=outer_stop_event
    )

    assert result is None  # stopped via the outer event, not a real barge-in trigger


def test_run_active_session_speaks_goodbye_and_unloads_on_stop_phrase(monkeypatch):
    unload_calls = []
    monkeypatch.setattr("jarvis.voice.stt.unload", lambda: unload_calls.append(1))
    _install_scripted_provider(monkeypatch, [])

    spoken = []
    transcripts = iter(["tchau jarvis"])

    conversation._run_active_session(
        listener=FakeListener(),
        record_utterance=lambda listener: b"",
        transcribe=lambda pcm: next(transcripts),
        speak=lambda text, stop_event=None: spoken.append(text),
    )

    assert spoken == [conversation.GOODBYE]
    assert unload_calls == [1]


def test_run_active_session_calls_llm_and_speaks_reply(monkeypatch):
    unload_calls = []
    monkeypatch.setattr("jarvis.voice.stt.unload", lambda: unload_calls.append(1))
    _install_scripted_provider(
        monkeypatch,
        [
            ProviderResponse(content="Olá, Senhor Nicholas."),
            ProviderResponse(content=""),  # unreachable, session ends after stop phrase below
        ],
    )

    spoken = []
    transcripts = iter(["oi jarvis", "tchau jarvis"])

    conversation._run_active_session(
        listener=FakeListener(),
        record_utterance=lambda listener: b"",
        transcribe=lambda pcm: next(transcripts),
        speak=lambda text, stop_event=None: spoken.append(text),
    )

    assert spoken == ["Olá, Senhor Nicholas.", conversation.GOODBYE]


def test_run_active_session_publishes_thinking_between_transcription_and_llm_call(monkeypatch):
    # Without this, the HUD kept showing "Ouvindo..." through the whole
    # LLM call too -- indistinguishable from actually still listening,
    # even though the user had already finished talking.
    from jarvis.visualizer import state as visualizer_state

    monkeypatch.setattr("jarvis.voice.stt.unload", lambda: None)
    published: list[str] = []
    monkeypatch.setattr(visualizer_state, "publish", lambda state, text="": published.append(state))

    state_when_llm_was_called = []

    def fake_send_turn(messages):
        state_when_llm_was_called.append(published[-1])
        return ""

    monkeypatch.setattr(conversation, "send_turn", fake_send_turn)
    transcripts = iter(["oi jarvis", "tchau jarvis"])

    conversation._run_active_session(
        listener=FakeListener(),
        record_utterance=lambda listener: b"",
        transcribe=lambda pcm: next(transcripts),
        speak=lambda text, stop_event=None: None,
    )

    assert state_when_llm_was_called == ["thinking"]


def test_run_active_session_forwards_stop_event_to_every_speak_call(monkeypatch):
    # "Desligar JARVIS" mid-sentence needs to interrupt speech in progress
    # (see tts.speak) -- that only works if a stop_event reaches every
    # speak() call, not just get dropped somewhere along the way. The
    # reply goes through _speak_with_barge_in now, so it receives that
    # function's own internal watch_event rather than the sentinel object
    # itself -- still real threading.Event instances, and the sentinel
    # still reaches speak() directly for GOODBYE (not barge-in-wrapped).
    unload_calls = []
    monkeypatch.setattr("jarvis.voice.stt.unload", lambda: unload_calls.append(1))
    _install_scripted_provider(monkeypatch, [ProviderResponse(content="Olá.")])

    received_stop_events = []
    transcripts = iter(["oi jarvis", "tchau jarvis"])
    sentinel_stop_event = threading.Event()

    conversation._run_active_session(
        listener=FakeListener(),
        record_utterance=lambda listener: b"",
        transcribe=lambda pcm: next(transcripts),
        speak=lambda text, stop_event=None: received_stop_events.append(stop_event),
        stop_event=sentinel_stop_event,
    )

    reply_stop_event, goodbye_stop_event = received_stop_events
    assert isinstance(reply_stop_event, threading.Event)
    assert goodbye_stop_event is sentinel_stop_event


def test_run_active_session_reply_can_be_barged_in_on_via_the_listener(monkeypatch):
    # Wires the real _speak_with_barge_in into _run_active_session (not a
    # mock) -- confirms the reply is actually watched for a barge-in
    # through whatever `listener` was passed in, and that being barged in
    # on doesn't break the session (it just moves on to listening again,
    # same as if the reply had finished normally).
    unload_calls = []
    monkeypatch.setattr("jarvis.voice.stt.unload", lambda: unload_calls.append(1))
    _install_scripted_provider(monkeypatch, [ProviderResponse(content="Uma resposta longa.")])

    listener = _ScriptedTriggerListener(triggers=["wake_word"])
    transcripts = iter(["oi jarvis", "tchau jarvis"])

    def blocking_speak(text, stop_event=None):
        if stop_event is not None:
            stop_event.wait(timeout=2)

    conversation._run_active_session(
        listener=listener,
        record_utterance=lambda listener: b"",
        transcribe=lambda pcm: next(transcripts),
        speak=blocking_speak,
    )

    assert unload_calls == [1]  # session still ended cleanly via the stop phrase afterward


def test_run_active_session_auto_goodbye_after_consecutive_empty_transcriptions(monkeypatch):
    unload_calls = []
    monkeypatch.setattr("jarvis.voice.stt.unload", lambda: unload_calls.append(1))
    _install_scripted_provider(monkeypatch, [])

    spoken = []

    conversation._run_active_session(
        listener=FakeListener(),
        record_utterance=lambda listener: b"",
        transcribe=lambda pcm: "",  # user walked away, never says a stop phrase
        speak=lambda text, stop_event=None: spoken.append(text),
    )

    assert spoken == [conversation.GOODBYE]
    assert unload_calls == [1]


class _FakeListener:
    def __init__(self, wait_results):
        self._wait_results = list(wait_results)
        self.closed = False

    def wait(self, stop_event=None):
        result = self._wait_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.closed = True


def test_run_voice_loop_recovers_from_a_listener_exception_instead_of_dying(monkeypatch):
    # The real bug this guards against: pvrecorder raised OSError after
    # another process briefly grabbed the mic, which used to kill the
    # whole thread silently -- see run_voice_loop's docstring.
    import jarvis.voice.wake_word as wake_word_module
    from jarvis.assistant import briefing, conversation
    from jarvis.voice import xtts_client

    monkeypatch.setattr(xtts_client, "ensure_worker_started", lambda: None)
    monkeypatch.setattr(briefing, "build_briefing", lambda: None)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    first = _FakeListener(wait_results=[RuntimeError("Failed to read from device.")])
    second = _FakeListener(wait_results=[None])  # recovered -- stops the loop cleanly
    to_construct = [first, second]
    monkeypatch.setattr(wake_word_module, "WakeWordListener", lambda: to_construct.pop(0))

    conversation.run_voice_loop()  # must return normally, not raise

    assert to_construct == []     # both were constructed
    assert first.closed is True   # closed during recovery, not leaked
    assert second.closed is True  # closed in the final `finally`


def test_run_voice_loop_gives_up_if_the_microphone_cannot_be_recreated(monkeypatch):
    # A transient failure recovers (see the test above); a genuinely broken
    # mic -- recreating the listener itself fails -- must still surface as
    # a real error, not loop forever or fail silently.
    import jarvis.voice.wake_word as wake_word_module
    from jarvis.assistant import briefing, conversation
    from jarvis.voice import xtts_client

    monkeypatch.setattr(xtts_client, "ensure_worker_started", lambda: None)
    monkeypatch.setattr(briefing, "build_briefing", lambda: None)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    first = _FakeListener(wait_results=[RuntimeError("Failed to read from device.")])
    remaining = [first]

    def factory():
        if not remaining:
            raise RuntimeError("microfone indisponível")
        return remaining.pop(0)

    monkeypatch.setattr(wake_word_module, "WakeWordListener", factory)

    with pytest.raises(RuntimeError, match="microfone indisponível"):
        conversation.run_voice_loop()

    assert first.closed is True  # not leaked even though recovery ultimately failed

    unload_calls = []
    monkeypatch.setattr("jarvis.voice.stt.unload", lambda: unload_calls.append(1))

    class RaisingProvider:
        def chat(self, messages, tool_specs):
            raise RuntimeError("boom")

    monkeypatch.setattr(llm_client, "_provider", RaisingProvider())

    transcripts = iter(["oi jarvis"])
    try:
        conversation._run_active_session(
            listener=FakeListener(),
            record_utterance=lambda listener: b"",
            transcribe=lambda pcm: next(transcripts),
            speak=lambda text, stop_event=None: None,
        )
    except RuntimeError:
        pass

    assert unload_calls == [1]
