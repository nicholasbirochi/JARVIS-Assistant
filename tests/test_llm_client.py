import copy

import pytest

from jarvis.assistant import llm_client
from jarvis.assistant.providers import ProviderResponse, ToolCallRequest


class ScriptedProvider:
    """Fake LocalLLMProvider: returns canned responses in sequence and
    records the exact `messages` list it was called with each time, so tests
    can assert history (including tool_calls) was preserved across turns."""

    def __init__(self, responses: list[ProviderResponse]):
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat(self, messages, tool_specs):
        self.calls.append(copy.deepcopy(messages))
        if not self._responses:
            raise AssertionError("ScriptedProvider ran out of canned responses")
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def reset_provider_singleton():
    original = llm_client._provider
    yield
    llm_client._provider = original


def test_send_turn_no_tool_calls_returns_content_directly():
    provider = ScriptedProvider([ProviderResponse(content="Olá, Senhor Nicholas.")])
    llm_client._provider = provider

    messages = [{"role": "user", "content": "oi"}]
    reply = llm_client.send_turn(messages)

    assert reply == "Olá, Senhor Nicholas."
    assert len(provider.calls) == 1
    assert messages[-1] == {"role": "assistant", "content": "Olá, Senhor Nicholas."}


def test_send_turn_executes_real_tool_and_preserves_history():
    provider = ScriptedProvider(
        [
            ProviderResponse(
                content="",
                tool_calls=[ToolCallRequest(name="list_supported_sites", arguments={})],
            ),
            ProviderResponse(content="Os sites suportados são esses."),
        ]
    )
    llm_client._provider = provider

    messages = [{"role": "user", "content": "quais sites você já suporta?"}]
    reply = llm_client.send_turn(messages)

    assert reply == "Os sites suportados são esses."
    assert len(provider.calls) == 2

    # First assistant turn must carry tool_calls so the model can make sense
    # of the following tool-role result on the next call.
    first_assistant_msg = provider.calls[1][-2]
    assert first_assistant_msg["role"] == "assistant"
    assert first_assistant_msg["tool_calls"] == [
        {"function": {"name": "list_supported_sites", "arguments": {}}}
    ]

    tool_result_msg = provider.calls[1][-1]
    assert tool_result_msg["role"] == "tool"
    assert tool_result_msg["tool_name"] == "list_supported_sites"
    assert "LinkedIn" in tool_result_msg["content"]


def test_send_turn_unknown_tool_name_reports_error_without_raising():
    provider = ScriptedProvider(
        [
            ProviderResponse(
                content="", tool_calls=[ToolCallRequest(name="ferramenta_fantasma", arguments={})]
            ),
            ProviderResponse(content="tudo bem"),
        ]
    )
    llm_client._provider = provider

    messages = [{"role": "user", "content": "faça algo impossível"}]
    llm_client.send_turn(messages)

    tool_result_msg = messages[-2]
    assert "desconhecida" in tool_result_msg["content"].lower()


def test_send_turn_stops_after_max_iterations():
    always_tool_call = ProviderResponse(
        content="", tool_calls=[ToolCallRequest(name="list_supported_sites", arguments={})]
    )
    provider = ScriptedProvider([always_tool_call] * llm_client.MAX_TOOL_ITERATIONS)
    llm_client._provider = provider

    messages = [{"role": "user", "content": "insista para sempre"}]
    reply = llm_client.send_turn(messages)

    assert "perdi" in reply.lower()
    assert len(provider.calls) == llm_client.MAX_TOOL_ITERATIONS
