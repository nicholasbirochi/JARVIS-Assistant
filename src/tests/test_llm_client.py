import copy

import pytest

from assistant import llm_client
from assistant.providers import ProviderResponse, ToolCallRequest
from resume import store
from resume.schema import Bilingual, Certification, PersonalInfo, Resume, SkillCategory


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


def test_send_turn_reports_tool_call_errors_instead_of_raising():
    # Real, observed failure: the model hallucinated an argument
    # (read_resume(path=...) -- read_resume takes none) -- this used to
    # propagate a TypeError all the way out of send_turn(), which
    # run_voice_loop misdiagnosed as a mic problem and silently dropped
    # the user's whole turn.
    provider = ScriptedProvider(
        [
            ProviderResponse(
                content="",
                tool_calls=[ToolCallRequest(name="read_resume", arguments={"path": "x"})],
            ),
            ProviderResponse(content="Desculpe, tive um problema -- pode repetir?"),
        ]
    )
    llm_client._provider = provider

    messages = [{"role": "user", "content": "me mostra o currículo"}]
    reply = llm_client.send_turn(messages)  # must not raise

    assert reply == "Desculpe, tive um problema -- pode repetir?"
    tool_result_msg = messages[-2]
    assert tool_result_msg["role"] == "tool"
    assert "erro" in tool_result_msg["content"].lower()


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


def test_specialization_summary_grounded_in_real_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RESUME_PATH", tmp_path / "resume.json")
    monkeypatch.setattr(store, "BACKUPS_DIR", tmp_path / "backups")
    resume = Resume(
        personal_info=PersonalInfo(full_name="Fulano", phone="A"),
        summary=Bilingual(pt="Resumo."),
        skills=[SkillCategory(category="Programming", items=["Python", "SQL"])],
        certifications=[Certification(name="Data Science for Beginners")],
    )
    store.save(resume)

    summary = llm_client._specialization_summary()

    assert "Python" in summary
    assert "SQL" in summary
    assert "Data Science for Beginners" in summary


def test_specialization_summary_empty_when_resume_unreadable(monkeypatch):
    def raise_it():
        raise FileNotFoundError("no resume yet")

    monkeypatch.setattr(store, "load", raise_it)

    assert llm_client._specialization_summary() == ""


def test_build_system_prompt_includes_specialization_when_available(monkeypatch):
    monkeypatch.setattr(llm_client, "_specialization_summary", lambda: "Habilidades técnicas dele: Python.")

    prompt = llm_client._build_system_prompt()

    assert "Python" in prompt
    assert "Senhor Nicholas" in prompt  # existing instructions preserved
    assert "Fale o mínimo necessário" in prompt  # conciseness rules preserved


def test_build_system_prompt_still_valid_when_resume_unreadable(monkeypatch):
    monkeypatch.setattr(llm_client, "_specialization_summary", lambda: "")

    prompt = llm_client._build_system_prompt()

    assert "Senhor Nicholas" in prompt
    assert "Fale o mínimo necessário" in prompt


def test_send_turn_uses_a_fresh_system_prompt_each_call(monkeypatch):
    monkeypatch.setattr(llm_client, "_build_system_prompt", lambda: "PROMPT DE TESTE")
    provider = ScriptedProvider([ProviderResponse(content="ok")])
    llm_client._provider = provider

    llm_client.send_turn([{"role": "user", "content": "oi"}])

    assert provider.calls[0][0] == {"role": "system", "content": "PROMPT DE TESTE"}
