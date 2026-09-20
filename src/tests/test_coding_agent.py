import copy
from pathlib import Path

import pytest

import config
from assistant import coding_agent
from assistant.coding_agent import WorkspaceViolation, _recover_tool_call_from_content, make_tools, run_coding_task
from assistant.providers import ProviderResponse, ToolCallRequest


class ScriptedProvider:
    """Same fake as test_llm_client.py's own -- canned responses in
    sequence, records every `messages` list it was called with."""

    def __init__(self, responses: list[ProviderResponse]):
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat(self, messages, tool_specs):
        self.calls.append(copy.deepcopy(messages))
        if not self._responses:
            raise AssertionError("ScriptedProvider ran out of canned responses")
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def set_coding_model(monkeypatch):
    monkeypatch.setattr(config, "CODING_MODEL", "qwen2.5-coder:14b")


def _patch_provider(monkeypatch, provider):
    monkeypatch.setattr(coding_agent, "get_provider", lambda model=None, host=None: provider)


def test_run_coding_task_refuses_when_no_model_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CODING_MODEL", None)

    result = run_coding_task("audite o projeto", str(tmp_path))

    assert "JARVIS_MODEL_CODING" in result


def test_run_coding_task_reports_missing_workspace(monkeypatch):
    provider = ScriptedProvider([])
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("audite o projeto", "/nao/existe/de/verdade")

    assert "não encontrado" in result.lower()
    assert provider.calls == []  # never even asks the model


def test_run_coding_task_no_tool_calls_returns_content_directly(monkeypatch, tmp_path):
    provider = ScriptedProvider([ProviderResponse(content="Análise pronta.")])
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("resuma o projeto", str(tmp_path))

    assert result == "Análise pronta."
    assert len(provider.calls) == 1


def test_run_coding_task_executes_real_read_file_tool_and_preserves_history(monkeypatch, tmp_path):
    (tmp_path / "config.py").write_text("LOCAL_MODEL = 'qwen2.5:7b'\n", encoding="utf-8")
    provider = ScriptedProvider(
        [
            ProviderResponse(
                content="", tool_calls=[ToolCallRequest(name="read_file", arguments={"path": "config.py"})]
            ),
            ProviderResponse(content="O modelo local é qwen2.5:7b."),
        ]
    )
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("qual modelo o config.py usa?", str(tmp_path))

    assert result == "O modelo local é qwen2.5:7b."
    assert len(provider.calls) == 2

    first_assistant_msg = provider.calls[1][-2]
    assert first_assistant_msg["tool_calls"] == [{"function": {"name": "read_file", "arguments": {"path": "config.py"}}}]

    tool_result_msg = provider.calls[1][-1]
    assert tool_result_msg["role"] == "tool"
    assert "qwen2.5:7b" in tool_result_msg["content"]


def test_run_coding_task_blocks_path_traversal_without_raising(monkeypatch, tmp_path):
    provider = ScriptedProvider(
        [
            ProviderResponse(
                content="", tool_calls=[ToolCallRequest(name="read_file", arguments={"path": "../../etc/passwd"})]
            ),
            ProviderResponse(content="Não posso acessar esse caminho."),
        ]
    )
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("leia /etc/passwd", str(tmp_path))

    assert result == "Não posso acessar esse caminho."
    tool_result_msg = provider.calls[1][-1]
    assert "fora do workspace" in tool_result_msg["content"].lower()


def test_run_coding_task_unknown_tool_reports_error_without_raising(monkeypatch, tmp_path):
    provider = ScriptedProvider(
        [
            ProviderResponse(content="", tool_calls=[ToolCallRequest(name="write_file", arguments={"path": "x"})]),
            ProviderResponse(content="Essa ferramenta ainda não existe."),
        ]
    )
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("edite um arquivo", str(tmp_path))

    assert result == "Essa ferramenta ainda não existe."
    tool_result_msg = provider.calls[1][-1]
    assert "desconhecida" in tool_result_msg["content"].lower()


def test_run_coding_task_gives_up_after_max_iterations(monkeypatch, tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    responses = [
        ProviderResponse(content="", tool_calls=[ToolCallRequest(name="read_file", arguments={"path": "a.txt"})])
        for _ in range(coding_agent.MAX_TOOL_ITERATIONS)
    ]
    provider = ScriptedProvider(responses)
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("nunca conclua", str(tmp_path))

    assert "limite de iterações" in result
    assert len(provider.calls) == coding_agent.MAX_TOOL_ITERATIONS


def test_make_tools_read_file_returns_content(tmp_path):
    (tmp_path / "nota.txt").write_text("conteúdo real", encoding="utf-8")
    read_file, _, _ = make_tools(tmp_path)

    assert read_file("nota.txt") == "conteúdo real"


def test_make_tools_read_file_reports_missing_file(tmp_path):
    read_file, _, _ = make_tools(tmp_path)

    assert "não encontrado" in read_file("nao_existe.txt").lower()


def test_make_tools_read_file_blocks_path_traversal(tmp_path):
    read_file, _, _ = make_tools(tmp_path)

    with pytest.raises(WorkspaceViolation):
        read_file("../../etc/passwd")


def test_make_tools_list_directory_lists_real_entries(tmp_path):
    (tmp_path / "b.py").write_text("", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    _, list_directory, _ = make_tools(tmp_path)

    entries = list_directory(".").splitlines()

    assert "b.py" in entries
    assert "sub/" in entries


def test_make_tools_list_directory_blocks_path_traversal(tmp_path):
    _, list_directory, _ = make_tools(tmp_path)

    with pytest.raises(WorkspaceViolation):
        list_directory("..")


def test_make_tools_run_tests_invokes_pytest_scoped_to_workspace(tmp_path, monkeypatch):
    _, _, run_tests = make_tools(tmp_path)
    captured = {}

    class FakeCompleted:
        stdout = "1 passed"
        stderr = ""

    def fake_run(args, cwd, capture_output, text, timeout):
        captured["args"] = args
        captured["cwd"] = cwd
        return FakeCompleted()

    monkeypatch.setattr(coding_agent.subprocess, "run", fake_run)

    result = run_tests()

    assert captured["args"][:3] == ["python3", "-m", "pytest"]
    assert captured["cwd"] == tmp_path
    assert "1 passed" in result


def test_make_tools_run_tests_blocks_path_traversal_in_target(tmp_path):
    _, _, run_tests = make_tools(tmp_path)

    with pytest.raises(WorkspaceViolation):
        run_tests(target="../../../etc")


def test_run_coding_task_recovers_a_real_tool_call_written_as_plain_json_content(monkeypatch, tmp_path):
    # Real, live-observed gap (qwen2.5-coder:14b via Ollama, 2026-09-20):
    # the model picks the right tool but this tag's chat template never
    # populates the structured tool_calls field -- it writes the call out
    # as JSON text in content instead.
    (tmp_path / "config.py").write_text("LOCAL_MODEL = 'qwen2.5:7b'\n", encoding="utf-8")
    provider = ScriptedProvider(
        [
            ProviderResponse(content='{\n  "name": "read_file",\n  "arguments": {"path": "config.py"}\n}'),
            ProviderResponse(content="O modelo local é qwen2.5:7b."),
        ]
    )
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("qual modelo o config.py usa?", str(tmp_path))

    assert result == "O modelo local é qwen2.5:7b."
    tool_result_msg = provider.calls[1][-1]
    assert tool_result_msg["role"] == "tool"
    assert "qwen2.5:7b" in tool_result_msg["content"]


def test_run_coding_task_recovers_a_tool_call_wrapped_in_a_markdown_code_fence(monkeypatch, tmp_path):
    (tmp_path / "a.txt").write_text("conteúdo", encoding="utf-8")
    provider = ScriptedProvider(
        [
            ProviderResponse(content='```json\n{"name": "read_file", "arguments": {"path": "a.txt"}}\n```'),
            ProviderResponse(content="Pronto."),
        ]
    )
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("leia a.txt", str(tmp_path))

    assert result == "Pronto."
    assert provider.calls[1][-1]["content"] == "conteúdo"


def test_recover_tool_call_from_content_ignores_ordinary_prose():
    assert _recover_tool_call_from_content("Aqui está a análise do arquivo.", {"read_file"}) is None


def test_recover_tool_call_from_content_ignores_json_for_an_unknown_tool():
    # Must never guess at a call for a tool that doesn't actually exist in
    # this run -- e.g. a hallucinated or unrelated JSON blob.
    content = '{"name": "delete_everything", "arguments": {}}'
    assert _recover_tool_call_from_content(content, {"read_file"}) is None


def test_recover_tool_call_from_content_ignores_json_missing_arguments_shape():
    content = '{"name": "read_file", "arguments": "config.py"}'
    assert _recover_tool_call_from_content(content, {"read_file"}) is None
