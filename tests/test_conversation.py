from jarvis.assistant import conversation
from jarvis.assistant import llm_client
from jarvis.assistant.providers import ProviderResponse


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
        speak=lambda text: spoken.append(text),
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
        speak=lambda text: spoken.append(text),
    )

    assert spoken == ["Olá, Senhor Nicholas.", conversation.GOODBYE]
    assert unload_calls == [1]


def test_run_active_session_auto_goodbye_after_consecutive_empty_transcriptions(monkeypatch):
    unload_calls = []
    monkeypatch.setattr("jarvis.voice.stt.unload", lambda: unload_calls.append(1))
    _install_scripted_provider(monkeypatch, [])

    spoken = []

    conversation._run_active_session(
        listener=FakeListener(),
        record_utterance=lambda listener: b"",
        transcribe=lambda pcm: "",  # user walked away, never says a stop phrase
        speak=lambda text: spoken.append(text),
    )

    assert spoken == [conversation.GOODBYE]
    assert unload_calls == [1]


def test_run_active_session_unloads_even_if_llm_raises(monkeypatch):
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
            speak=lambda text: None,
        )
    except RuntimeError:
        pass

    assert unload_calls == [1]
