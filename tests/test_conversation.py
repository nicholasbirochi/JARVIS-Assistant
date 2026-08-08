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
    pass


def _install_scripted_provider(monkeypatch, responses):
    monkeypatch.setattr(llm_client, "_provider", ScriptedProvider(responses))


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
    assert unload_calls == [1]


def test_run_active_session_forwards_stop_event_to_every_speak_call(monkeypatch):
    # "Desligar JARVIS" mid-sentence needs to interrupt speech in progress
    # (see tts.speak) -- that only works if the same stop_event reaches
    # every speak() call, not just get dropped somewhere along the way.
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

    assert received_stop_events == [sentinel_stop_event, sentinel_stop_event]


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
    from jarvis.voice import xtts_engine

    monkeypatch.setattr(xtts_engine, "preload_in_background", lambda: None)
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
    from jarvis.voice import xtts_engine

    monkeypatch.setattr(xtts_engine, "preload_in_background", lambda: None)
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
