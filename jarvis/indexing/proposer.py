"""Calls the local model to propose résumé changes from one scanned file's
text, then merges the model's judgment (value/confidence/quote) with
code-derived provenance (source_path/source_type/read_at) into Evidence."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from jarvis.assistant.providers import get_provider
from jarvis.indexing import scanner
from jarvis.indexing.proposals import LLMProposalBatch, ProposedChange, UnreadableFile
from jarvis.resume import store
from jarvis.resume.schema import Evidence, Resume

SYSTEM_PROMPT = """\
Você analisa UM documento pessoal (currículo, certificado de curso, ou \
projeto acadêmico/pessoal) para propor atualizações ao perfil profissional \
canônico do Nicholas, cujo estado atual (em JSON) será fornecido.

Para cada fato relevante e novo (ou diferente do que já está registrado) \
encontrado no documento, produza uma mudança:
- kind="update_field": USE APENAS para um índice de lista que JÁ EXISTE no \
JSON fornecido (ex.: se "certifications" tem 7 itens, índices válidos são \
0 a 6 -- NUNCA proponha "certifications.7.*"). Informe "field_path" usando \
o mesmo formato de caminho com pontos do JSON fornecido (ex.: \
"personal_info.phone", "certifications.0.hours" -- NUNCA \
"certifications[0].hours"). Informe "value" com o novo valor, SEMPRE como \
string -- para números, booleanos ou listas, envie a representação em JSON \
como texto (ex.: "42", "true", '["a", "b"]'). Não deixe "value" vazio.
- kind="new_item": use para QUALQUER item que ainda não está no perfil \
(uma nova certificação, um novo projeto, uma nova experiência) -- inclusive \
quando você só sabe uma parte dos campos desse item. NUNCA divida um item \
novo em várias mudanças "update_field" apontando para um índice \
inexistente -- junte tudo que você sabe sobre esse item em UM único \
"item" (os campos que não aparecerem no documento podem ficar de fora ou \
nulos). Informe "list_field" com o nome da lista ("certifications", \
"projects", "experience", "education", "languages") e "item" como um \
objeto com os campos daquele tipo de item (ex.: para certifications: name, \
hours, status "in_progress"/"completed", date).

Para cada mudança, inclua também:
- "quote": um trecho literal do documento que sustenta essa mudança.
- "confidence": de 0 a 1, sua confiança de que essa é uma leitura correta.
- "rationale": uma frase curta explicando por que propôs essa mudança.

Não invente informações que não estejam no documento. Não proponha mudanças \
triviais ou irrelevantes (ex.: reformatar texto). Se o documento não \
contiver nenhum fato profissional novo ou relevante, retorne uma lista vazia.

Cuidado especial com "certifications": só proponha uma nova certificação se \
o documento efetivamente descrever um curso/certificado concluído ou em \
andamento (linguagem como "certificado", "curso", "concluí", carga \
horária, plataforma de ensino). Um arquivo de código-fonte ou de \
dependências (ex.: requirements.txt, package.json, imports) que apenas \
menciona o nome de uma biblioteca/framework NÃO é evidência de certificação \
-- nesse caso, no máximo é evidência de uso da tecnologia em um projeto \
("list_field"="projects"), nunca de um curso feito.
"""


def _user_content(text: str, resume: Resume, source_name: str) -> str:
    resume_json = json.dumps(resume.model_dump(mode="json"), ensure_ascii=False)
    return (
        f"=== Perfil atual (JSON) ===\n{resume_json}\n\n"
        f"=== Documento: {source_name} ===\n{text}"
    )


def propose_changes_for_file(path: Path, text: str, resume: Resume) -> LLMProposalBatch:
    provider = get_provider()
    raw = provider.structured_chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_content(text, resume, path.name)},
        ],
        json_schema=LLMProposalBatch.model_json_schema(),
    )
    return LLMProposalBatch.model_validate(raw)


_SOURCE_TYPE_BY_SUFFIX = {".docx": "docx", ".pdf": "pdf", ".txt": "txt", ".md": "md"}
_BRACKET_INDEX_RE = re.compile(r"\[(\d+)\]")


def _normalize_field_path(field_path: str) -> str:
    """Despite the prompt instructing dot-only paths, the model sometimes
    still emits bracket notation (e.g. "certifications[0].hours") --
    normalize it defensively rather than let a well-formed proposal fail to
    apply at review time over a cosmetic path format."""
    return _BRACKET_INDEX_RE.sub(r".\1", field_path).replace("..", ".")


def _update_field_would_apply(resume: Resume, field_path: str, value: Any) -> bool:
    try:
        store.update_field(resume, field_path, value)
        return True
    except (store.FieldPathError, ValidationError):
        return False


def _new_item_would_apply(resume: Resume, list_field: str, item: dict) -> bool:
    try:
        store.append_item(resume, list_field, item)
        return True
    except (store.FieldPathError, ValidationError):
        return False


def attach_evidence(batch: LLMProposalBatch, path: Path, resume: Resume) -> list[ProposedChange]:
    read_at = datetime.now(timezone.utc).isoformat()
    source_type = _SOURCE_TYPE_BY_SUFFIX[path.suffix.lower()]
    source_path = scanner.normalize_path_key(path)

    out: list[ProposedChange] = []
    for change in batch.changes:
        if change.field_path:
            change.field_path = _normalize_field_path(change.field_path)

        evidence = Evidence(
            source_path=source_path,
            source_type=source_type,
            read_at=read_at,
            snippet=change.quote,
            confidence=change.confidence,
            review_status="pending",
        )

        existing_value = None
        if change.kind == "update_field" and change.field_path:
            try:
                existing_value = store.get_field(resume, change.field_path)
            except store.FieldPathError:
                existing_value = None  # LLM hallucinated a bad path -- reviewer will reject

        # The local model occasionally emits a value/item that doesn't
        # actually fit the target field's shape (a nested object where a
        # plain number is expected, a required field missing, even literal
        # placeholder text like "some value here"). Rather than make the
        # human reject obvious garbage by hand one entry at a time, drop
        # anything that wouldn't even pass the same validation store.py
        # applies at write time -- this doesn't touch `resume` (update_field
        # / append_item always return a new object), it's a pure dry run.
        if change.kind == "update_field":
            if not change.field_path:
                continue
            proposed_value = store.coerce_value(change.value)
            if not _update_field_would_apply(resume, change.field_path, proposed_value):
                continue
        elif change.kind == "new_item":
            if not change.list_field:
                continue
            proposed_value = {**change.item, "evidence": [evidence.model_dump(mode="json")]}
            if not _new_item_would_apply(resume, change.list_field, proposed_value):
                continue
        else:
            continue

        conflict = (
            change.kind == "update_field"
            and existing_value is not None
            and existing_value != proposed_value
        )

        out.append(
            ProposedChange(
                kind=change.kind,
                field_path=change.field_path,
                list_field=change.list_field,
                proposed_value=proposed_value,
                existing_value=existing_value,
                evidence=[evidence],
                conflict=conflict,
                rationale=change.rationale,
            )
        )
    return out


def unreadable_file_entry(path: Path, reason: str = "sem texto extraível") -> UnreadableFile:
    return UnreadableFile(
        path=scanner.normalize_path_key(path),
        reason=reason,
        detected_at=datetime.now(timezone.utc).isoformat(),
    )


def dedupe_update_field_changes(changes: list[ProposedChange]) -> list[ProposedChange]:
    """Several source files commonly yield the identical update_field
    proposal -- e.g. a "Brasil" and an "International" résumé variant both
    reporting the same corrected phone number. Collapse exact duplicates
    (same field_path + same proposed_value) into one change with every
    source's evidence attached, instead of asking the reviewer to
    accept/reject the same fact several times in a row.

    new_item changes are deliberately left untouched: whether two items are
    "the same" needs fuzzy matching (name similarity, overlapping dates...)
    that exact-value comparison can't do safely -- getting it wrong risks
    silently dropping a real, distinct item. Out of scope here."""
    deduped: list[ProposedChange] = []
    index_by_key: dict[tuple[str, str], int] = {}
    for change in changes:
        if change.kind != "update_field":
            deduped.append(change)
            continue
        key = (change.field_path or "", json.dumps(change.proposed_value, sort_keys=True, default=str))
        existing_index = index_by_key.get(key)
        if existing_index is None:
            index_by_key[key] = len(deduped)
            deduped.append(change)
        else:
            deduped[existing_index].evidence.extend(change.evidence)
    return deduped
