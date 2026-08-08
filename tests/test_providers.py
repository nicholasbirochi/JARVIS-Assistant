import json
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from jarvis import config
from jarvis.assistant.providers import OllamaProvider, get_provider
from jarvis.assistant.tool_schema import ToolSpec


@dataclass
class FakeFunction:
    name: str
    arguments: dict


@dataclass
class FakeToolCall:
    function: FakeFunction


@dataclass
class FakeMessage:
    content: str
    tool_calls: list = field(default_factory=list)


class FakeClient:
    def __init__(self, response_message: FakeMessage):
        self._response_message = response_message
        self.last_call_kwargs: dict | None = None

    def chat(self, **kwargs):
        self.last_call_kwargs = kwargs
        return SimpleNamespace(message=self._response_message)


def test_get_provider_default_is_ollama(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
    provider = get_provider()
    assert isinstance(provider, OllamaProvider)


def test_get_provider_unknown_raises(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "something-else")
    with pytest.raises(ValueError):
        get_provider()


def test_ollama_provider_chat_no_tool_calls():
    fake_client = FakeClient(FakeMessage(content="olá", tool_calls=[]))
    provider = OllamaProvider(model="qwen2.5:14b", host="http://x", client=fake_client)

    response = provider.chat(messages=[{"role": "user", "content": "oi"}], tool_specs=[])

    assert response.content == "olá"
    assert response.tool_calls == []
    assert fake_client.last_call_kwargs["tools"] == []


def test_ollama_provider_chat_with_tool_calls():
    fake_client = FakeClient(
        FakeMessage(
            content="",
            tool_calls=[FakeToolCall(function=FakeFunction(name="read_resume", arguments={}))],
        )
    )
    spec = ToolSpec(name="read_resume", description="d", parameters={"type": "object", "properties": {}, "required": []})
    provider = OllamaProvider(model="qwen2.5:14b", host="http://x", client=fake_client)

    response = provider.chat(messages=[{"role": "user", "content": "leia meu currículo"}], tool_specs=[spec])

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "read_resume"
    assert response.tool_calls[0].arguments == {}
    assert fake_client.last_call_kwargs["tools"][0]["function"]["name"] == "read_resume"


def test_ollama_provider_structured_chat_parses_json():
    fake_client = FakeClient(FakeMessage(content=json.dumps({"a": 1})))
    provider = OllamaProvider(model="qwen2.5:14b", host="http://x", client=fake_client)

    result = provider.structured_chat(messages=[{"role": "user", "content": "x"}], json_schema={"type": "object"})

    assert result == {"a": 1}
    assert fake_client.last_call_kwargs["options"] == {"temperature": 0}


def test_ollama_provider_passes_keep_alive_on_chat():
    # Ollama's own default keep-alive (5 minutes) was found to be the real
    # cost behind slow replies in practice -- any gap between JARVIS
    # activations longer than that forces a full cold model reload. This
    # must be sent on every request, not assumed to be a server setting.
    fake_client = FakeClient(FakeMessage(content="olá", tool_calls=[]))
    provider = OllamaProvider(model="qwen2.5:7b", host="http://x", client=fake_client, keep_alive="30m")

    provider.chat(messages=[{"role": "user", "content": "oi"}], tool_specs=[])

    assert fake_client.last_call_kwargs["keep_alive"] == "30m"


def test_ollama_provider_passes_keep_alive_on_structured_chat():
    fake_client = FakeClient(FakeMessage(content="{}"))
    provider = OllamaProvider(model="qwen2.5:7b", host="http://x", client=fake_client, keep_alive="30m")

    provider.structured_chat(messages=[{"role": "user", "content": "x"}], json_schema={"type": "object"})

    assert fake_client.last_call_kwargs["keep_alive"] == "30m"


def test_get_provider_passes_keep_alive_from_config(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(config, "OLLAMA_KEEP_ALIVE", "1h")

    provider = get_provider()

    assert provider._keep_alive == "1h"
