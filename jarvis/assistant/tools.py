"""The tool surface the local model uses to read/edit the résumé and
(eventually) push it to job sites. Plain functions with Google-style
docstrings -- Ollama's client introspects these directly into tool schemas,
no decorator needed. Each call re-loads/re-saves data/resume.json rather than
sharing in-memory state -- this is a low-throughput personal CLI, so the
extra file IO is irrelevant and it guarantees tools never see stale state."""

from __future__ import annotations

import json

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


TOOLS = [read_resume, update_resume_field, list_supported_sites, push_resume_to_site]
