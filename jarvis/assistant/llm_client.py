"""Hand-written tool-call loop for the live voice/text conversation, driven
through the LocalLLMProvider abstraction (jarvis/assistant/providers.py) --
no direct dependency on `ollama` here, so swapping providers later doesn't
touch this file."""

from __future__ import annotations

from jarvis.assistant.providers import LocalLLMProvider, get_provider
from jarvis.assistant.tool_schema import functions_to_tool_specs
from jarvis.assistant.tools import TOOLS

SYSTEM_PROMPT = """\
Você é o JARVIS, o assistente pessoal do Nicholas. Fale sempre em português \
do Brasil, de forma direta e respeitosa, tratando-o como "Senhor Nicholas" \
quando apropriado -- sem exagerar na formalidade.

Sua função hoje é conversar sobre o currículo do Nicholas: consultar dados \
(ferramenta read_resume), editar campos quando ele pedir (ferramenta \
update_resume_field), e informar quais sites de vagas já são suportados \
(list_supported_sites) ou tentar publicar nele (push_resume_to_site -- ainda \
não implementado para nenhum site, apenas explique isso quando pedido).

Sempre que for editar um campo, primeiro use read_resume para confirmar o \
caminho e o valor atual antes de chamar update_resume_field. Depois de \
editar, confirme em uma frase curta o que mudou.

Fale o mínimo necessário. Cada resposta deve ter, no máximo, uma ou duas \
frases curtas -- só o essencial para responder ao que foi perguntado, sem \
introdução, sem repetir o que o Nicholas disse, sem markdown, listas, ou \
oferecer ajuda extra que não foi pedida ("posso ajudar com mais algo?" só \
se fizer sentido de verdade, não por padrão). Se a resposta puder ser uma \
frase, não use duas.
"""

MAX_TOOL_ITERATIONS = 8

_provider: LocalLLMProvider | None = None
_functions_by_name = {f.__name__: f for f in TOOLS}
_tool_specs = functions_to_tool_specs(TOOLS)


def _get_provider() -> LocalLLMProvider:
    global _provider
    if _provider is None:
        _provider = get_provider()
    return _provider


def send_turn(messages: list[dict]) -> str:
    """Runs the tool loop for the conversation so far (last entry must be the
    new user turn already appended by the caller). Mutates `messages` in
    place with every assistant/tool turn produced, and returns the final
    assistant text to speak back."""

    provider = _get_provider()

    for _ in range(MAX_TOOL_ITERATIONS):
        response = provider.chat(
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
            tool_specs=_tool_specs,
        )

        # Preserve tool_calls on the replayed assistant turn -- the model
        # needs to see its own prior calls to make sense of the "tool"-role
        # results that follow, or multi-turn tool history silently breaks.
        assistant_message: dict = {"role": "assistant", "content": response.content}
        if response.tool_calls:
            assistant_message["tool_calls"] = [
                {"function": {"name": call.name, "arguments": call.arguments}}
                for call in response.tool_calls
            ]
        messages.append(assistant_message)

        if not response.tool_calls:
            return response.content

        for call in response.tool_calls:
            function = _functions_by_name.get(call.name)
            if function is None:
                output = f"Ferramenta desconhecida: {call.name}"
            else:
                # A real, observed failure: the local model hallucinated an
                # argument that doesn't exist (read_resume(path=...) --
                # read_resume takes none) -- TypeError propagated all the
                # way out of send_turn(), which run_voice_loop's broad
                # exception handler then misdiagnosed as a mic problem and
                # "recovered" from, silently dropping the user's turn with
                # no reply at all. A bad tool call is the model's mistake to
                # see and correct, not a reason to blow up the whole turn.
                try:
                    output = function(**call.arguments)
                except Exception as exc:
                    output = f"Erro ao executar {call.name}: {exc}"
            messages.append({"role": "tool", "content": str(output), "tool_name": call.name})

    return "Desculpe, Senhor Nicholas, me perdi tentando executar essa ação. Pode repetir?"
