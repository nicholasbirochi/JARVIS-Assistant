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
