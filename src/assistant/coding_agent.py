"""First step toward the "Apple Private AI Cluster" blueprint's real
near-term goal: a local coding agent capable enough to replace
Claude/Codex for real engineering work, running through the same
LocalLLMProvider abstraction (assistant/providers.py) as the voice
assistant's own tool loop (assistant/llm_client.py) -- same pattern,
different model and a much narrower tool surface.

READ-ONLY FIRST VERSION, on purpose: no write_file/edit/run_shell tool
yet. Mirrors this project's own established discipline (see
sites/gupy.py, sites/infojobs.py -- every mutating action sits behind
an explicit confirmed=True/finalize=True gate, tested live before ever
being trusted) and the blueprint's own "primeira execução = auditoria
somente" rule. A write/execute step can be added later the same
deliberate way every other real action in this project was earned, not
assumed safe by default.

Current model recommendation (2026-09-20, see
JARVIS_Apple_Private_AI_Cluster_MASTER_v3.zip's own
07_MODEL_RUNTIME_STRATEGY.md for the full reasoning, confirmed live):
`qwen2.5-coder:14b` on the current 24 GB machine (~9 GB, fits
comfortably); `qwen3-coder:30b` once on the future 64 GB Mac mini.
Neither is hardcoded here -- set JARVIS_MODEL_CODING in .env.
run_coding_task() refuses to run with no model configured rather than
silently falling back to config.LOCAL_MODEL (the voice assistant's own
model, deliberately small/fast for conversational latency -- see that
constant's own comment -- not sized or chosen for coding capability).

Workspace-scoped by design (a real, named concern in the blueprint's
own SECURITY/THREAT_MODEL.md -- path traversal): every tool here takes
a path relative to the given workspace root and refuses anything that
resolves outside it, the same deny-by-default principle as the
blueprint's own SECURITY/POLICY_BASELINE.yaml."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Callable

from assistant.providers import LocalLLMProvider, ToolCallRequest, get_provider
from assistant.tool_schema import functions_to_tool_specs

MAX_TOOL_ITERATIONS = 12
_READ_FILE_CHAR_LIMIT = 20_000
_TEST_OUTPUT_CHAR_LIMIT = 4_000
_TEST_TIMEOUT_SECONDS = 120

_SYSTEM_PROMPT = """\
Você é um agente de coding local, rodando inteiramente na máquina do \
usuário (sem nenhuma chamada de rede externa). Sua tarefa é ajudar em \
tarefas reais de engenharia de software dentro do workspace indicado.

Nesta primeira versão você é SOMENTE LEITURA: pode listar diretórios, \
ler arquivos e rodar a suíte de testes (pytest) -- nunca editar ou \
criar arquivos, nunca rodar comandos além dos testes. Se a tarefa \
pedida exigir escrever código, responda com a mudança proposta em \
texto (um trecho claro ou diff) para o usuário aplicar manualmente -- \
não finja que aplicou algo que não foi de fato escrito em disco.

Seja direto e técnico. Não invente conteúdo de arquivo que você não \
leu de verdade com read_file.

Responda exatamente o que foi perguntado, de forma direta e objetiva -- \
se a pergunta pede um dado específico (um nome de variável, um valor, \
uma linha), dê esse dado primeiro, sem um resumo geral do arquivo \
inteiro antes ou depois. Um resumo amplo só quando isso é literalmente \
o que foi pedido."""


class WorkspaceViolation(Exception):
    """Raised when a tool call tries to reach outside the workspace root."""


def _resolve_within_workspace(workspace: Path, relative_path: str) -> Path:
    candidate = (workspace / relative_path).resolve()
    if not candidate.is_relative_to(workspace):
        raise WorkspaceViolation(f"Caminho fora do workspace: {relative_path!r}")
    return candidate


def make_tools(workspace: Path) -> list[Callable]:
    """Builds the read-only tool set bound to one specific workspace root
    -- a fresh closure per call so two concurrent tasks (different
    workspaces) never share or leak each other's path scoping."""

    def read_file(path: str) -> str:
        """Lê o conteúdo de um arquivo de texto dentro do workspace.

        Args:
            path: caminho relativo ao workspace (ex.: "src/config.py").
        """
        target = _resolve_within_workspace(workspace, path)
        if not target.is_file():
            return f"Arquivo não encontrado: {path}"
        try:
            return target.read_text(encoding="utf-8")[:_READ_FILE_CHAR_LIMIT]
        except UnicodeDecodeError:
            return f"Arquivo binário, não é possível ler como texto: {path}"

    def list_directory(path: str = ".") -> str:
        """Lista arquivos e subpastas de um diretório dentro do workspace.

        Args:
            path: caminho relativo ao workspace (padrão: raiz do workspace).
        """
        target = _resolve_within_workspace(workspace, path)
        if not target.is_dir():
            return f"Diretório não encontrado: {path}"
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())
        return "\n".join(entries) or "(vazio)"

    def run_tests(target: str = "") -> str:
        """Roda a suíte de testes (pytest) dentro do workspace -- somente
        leitura, nunca modifica nada.

        Args:
            target: caminho ou nó de teste específico (padrão: suíte inteira).
        """
        args = ["python3", "-m", "pytest", "-q"]
        if target:
            args.append(_resolve_within_workspace(workspace, target).as_posix())
        try:
            result = subprocess.run(
                args, cwd=workspace, capture_output=True, text=True, timeout=_TEST_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired:
            return f"Testes excederam o tempo limite ({_TEST_TIMEOUT_SECONDS}s)."
        return (result.stdout + result.stderr)[-_TEST_OUTPUT_CHAR_LIMIT:]

    return [read_file, list_directory, run_tests]


def _recover_tool_call_from_content(content: str, known_tool_names: set[str]) -> ToolCallRequest | None:
    """Real, live-observed gap (2026-09-20, qwen2.5-coder:14b via Ollama):
    the model correctly understood a tool-use task and picked the right
    tool, but this particular tag's chat template never populated
    Ollama's own structured `message.tool_calls` field -- it wrote the
    call out as plain JSON text in the ordinary content instead
    (confirmed live, reproducibly, not a one-off glitch). Silently
    treating that JSON blob as the model's final answer -- which is
    what happened before this existed -- is a real, confirmed failure
    mode, not a hypothetical one.

    Deliberately conservative: only recovers a call when the parsed
    object is unambiguously {"name", "arguments"}-shaped AND the name
    matches one of THIS run's own real tools -- never guesses at a call
    for an unknown or hallucinated tool name."""
    stripped = content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fenced:
        stripped = fenced.group(1).strip()
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    name, arguments = parsed.get("name"), parsed.get("arguments")
    if name not in known_tool_names or not isinstance(arguments, dict):
        return None
    return ToolCallRequest(name=name, arguments=arguments)


def run_coding_task(task: str, workspace_dir: str) -> str:
    """Executa uma tarefa de coding, somente leitura, usando o modelo
    configurado em JARVIS_MODEL_CODING. Retorna a resposta final do
    modelo (texto) -- nunca aplica nenhuma mudança em disco."""
    from config import CODING_MODEL

    if not CODING_MODEL:
        return (
            "JARVIS_MODEL_CODING não está configurado -- defina no .env antes "
            "de usar o agente de coding (ver assistant/coding_agent.py)."
        )

    workspace = Path(workspace_dir).resolve()
    if not workspace.is_dir():
        return f"Workspace não encontrado: {workspace_dir}"

    tools = make_tools(workspace)
    functions_by_name = {f.__name__: f for f in tools}
    tool_specs = functions_to_tool_specs(tools)

    provider: LocalLLMProvider = get_provider(model=CODING_MODEL)
    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for _ in range(MAX_TOOL_ITERATIONS):
        response = provider.chat(messages=messages, tool_specs=tool_specs)

        tool_calls = response.tool_calls
        if not tool_calls:
            recovered = _recover_tool_call_from_content(response.content, set(functions_by_name))
            if recovered is not None:
                tool_calls = [recovered]

        # Same reasoning as llm_client.py's send_turn(): the model needs to
        # see its own prior calls to make sense of the "tool"-role results
        # that follow, or multi-turn tool history silently breaks.
        assistant_message: dict = {"role": "assistant", "content": response.content}
        if tool_calls:
            assistant_message["tool_calls"] = [
                {"function": {"name": call.name, "arguments": call.arguments}} for call in tool_calls
            ]
        messages.append(assistant_message)

        if not tool_calls:
            return response.content

        for call in tool_calls:
            function = functions_by_name.get(call.name)
            if function is None:
                output = f"Ferramenta desconhecida: {call.name}"
            else:
                try:
                    output = function(**call.arguments)
                except WorkspaceViolation as exc:
                    output = str(exc)
                except Exception as exc:  # noqa: BLE001 -- a bad tool call is the model's mistake to see, not a reason to crash the task
                    output = f"Erro ao executar {call.name}: {exc}"
            messages.append({"role": "tool", "content": str(output), "tool_name": call.name})

    return "Não consegui concluir a tarefa dentro do limite de iterações."
