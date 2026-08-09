"""The tool surface the local model uses to read/edit the résumé, push it
to job sites (eventually), and relay a prompt to Claude Code. Plain
functions with Google-style docstrings -- Ollama's client introspects
these directly into tool schemas, no decorator needed. Each résumé-editing
call re-loads/re-saves data/resume.json rather than sharing in-memory
state -- this is a low-throughput personal CLI, so the extra file IO is
irrelevant and it guarantees tools never see stale state.

prepare_claude_prompt() is the one tool here that isn't about the résumé
at all: it's how "tell Claude Code to do X" by voice actually reaches
Claude Code -- there's no API for JARVIS to inject text into a running
Claude Code conversation, so it copies a prompt to the clipboard (and logs
it locally as a durability net) for the user to paste themselves,
wherever/whenever they choose. That choice is deliberate, not a
limitation to route around: which project a request is even about is
Nicholas's call, not something to guess."""

from __future__ import annotations

import json
import subprocess

from pydantic import ValidationError

from jarvis.resume import store

SUPPORTED_SITES = ["LinkedIn", "Gupy", "Catho", "InfoJobs", "Vagas.com", "Indeed"]


def read_resume() -> str:
    """Retorna o currículo completo do Nicholas em JSON.

    Use sempre que precisar consultar os dados atuais do currículo, antes de
    responder uma pergunta sobre ele ou antes de editar um campo.
    """
    resume = store.load()
    return json.dumps(resume.model_dump(mode="json"), ensure_ascii=False)


def update_resume_field(path: str, value: str) -> str:
    """Atualiza um único campo do currículo, identificado por um caminho com pontos.

    Args:
        path: Caminho do campo, ex.: "personal_info.phone" ou "experience.0.title.pt".
              Índices de lista são números (0, 1, 2...).
        value: Novo valor como string. Para campos booleanos, numéricos ou listas,
               envie como JSON (ex.: "true", "42", '["item1", "item2"]').
    """
    resume = store.load()
    try:
        updated = store.update_field(resume, path, store.coerce_value(value), source="voice")
    except store.FieldPathError as exc:
        return f"Erro: {exc}"
    except ValidationError as exc:
        return f"Valor inválido para {path}: {exc}"
    store.save(updated)
    return f"Campo {path} atualizado com sucesso."


def list_supported_sites() -> str:
    """Lista os sites de vagas que o JARVIS já sabe (ou vai saber) atualizar."""
    return ", ".join(SUPPORTED_SITES)


def push_resume_to_site(site: str) -> str:
    """Publica o currículo atual no site de vagas indicado.

    Args:
        site: Nome do site, ex.: "LinkedIn", "Gupy", "Catho", "InfoJobs",
              "Vagas.com" ou "Indeed".
    """
    if site not in SUPPORTED_SITES:
        return f"'{site}' não está na lista de sites suportados: {', '.join(SUPPORTED_SITES)}."
    return (
        f"A atualização automática do {site} ainda não foi implementada "
        "-- isso chega numa fase futura do projeto."
    )


def prepare_claude_prompt(prompt: str) -> str:
    """Copia um prompt para a área de transferência, pronto para colar numa conversa com o Claude Code.

    Use quando o Nicholas pedir para mudar algo no código do JARVIS, em outro
    projeto, ou quiser passar um pedido para o Claude Code implementar. Escreva
    você mesmo o prompt completo e bem estruturado, com todo o contexto
    necessário -- não apenas repita a fala dele ao pé da letra, capriche como se
    estivesse escrevendo para um desenvolvedor de verdade. Ele mesmo decide, ao
    colar, se é sobre este projeto ou outro -- por isso nunca invente qual
    projeto/arquivo é, a menos que o Nicholas tenha dito.

    Args:
        prompt: O prompt completo, pronto para ser colado no Claude Code.
    """
    try:
        subprocess.run(["pbcopy"], input=prompt.encode("utf-8"), check=True)
    except Exception as exc:
        return f"Não consegui copiar para a área de transferência: {exc}"

    _log_claude_prompt(prompt)
    return "Prompt copiado para a área de transferência -- já pode colar numa conversa com o Claude Code."


def _log_claude_prompt(prompt: str) -> None:
    """Best-effort durability net so a prompt isn't lost if it isn't
    pasted right away -- never raises, since a logging hiccup here must
    never turn an already-successful clipboard copy into a reported
    failure."""
    try:
        from datetime import datetime, timezone

        from jarvis.config import LOCAL_STATE_DIR

        log_path = LOCAL_STATE_DIR / "claude_prompts.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"--- {timestamp} ---\n{prompt}\n\n")
    except Exception:
        pass


TOOLS = [read_resume, update_resume_field, list_supported_sites, push_resume_to_site, prepare_claude_prompt]
