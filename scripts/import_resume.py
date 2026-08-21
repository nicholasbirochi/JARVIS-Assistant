"""One-off Phase 0 script: consolidate the two ATS résumé docx files (pt/en)
into the canonical data/resume.json, plus a human-reviewable side-by-side
report at data/review/resume_review.md.

Runs entirely against the local Ollama model -- no cloud API, no API key.
Read-only against the OneDrive source folder -- never writes back there.
Re-run any time the source résumés change; re-review the output before
trusting it, since this is the permanent source of truth from here on.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from assistant.providers import get_provider  # noqa: E402
from config import (  # noqa: E402
    RESUME_PATH,
    RESUME_SCHEMA_PATH,
    REVIEW_DIR,
    SOURCE_RESUME_DOCS,
)
from resume.docx_extract import extract_text  # noqa: E402
from resume.schema import Resume  # noqa: E402

SYSTEM_PROMPT = """\
Você recebe o texto bruto de duas versões (português e inglês) do mesmo \
currículo em formato ATS. Sua tarefa é consolidá-las em UM único objeto \
estruturado, seguindo exatamente o JSON schema fornecido.

Regras:
- Combine cada item semanticamente equivalente (ex.: a mesma experiência \
profissional descrita em pt e en) em UMA entrada, preenchendo os campos \
bilíngues (pt/en) quando o schema pedir.
- Não invente informações que não estejam em nenhuma das duas fontes.
- Preserve datas, números e nomes próprios exatamente como aparecem na fonte.
- Campos de formação e certificações em andamento devem usar status \
"in_progress"; os já concluídos usam "completed".
"""


def main() -> None:
    docs = [Path(p) for p in SOURCE_RESUME_DOCS]
    for doc in docs:
        if not doc.exists():
            raise SystemExit(f"Arquivo fonte não encontrado: {doc}")

    texts = {doc.name: extract_text(doc) for doc in docs}
    schema = json.loads(RESUME_SCHEMA_PATH.read_text(encoding="utf-8"))

    user_content = "\n\n".join(
        f"=== {name} ===\n{text}" for name, text in texts.items()
    )

    provider = get_provider()
    data = provider.structured_chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        json_schema=schema,
    )
    data.setdefault("meta", {})["source_documents"] = [d.name for d in docs]

    resume = Resume.model_validate(data)

    RESUME_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESUME_PATH.write_text(
        json.dumps(resume.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    review_path = REVIEW_DIR / "resume_review.md"
    review_sections = ["# Revisão da importação do currículo\n"]
    review_sections.append("## Currículo consolidado (resume.json)\n")
    review_sections.append("```json\n" + json.dumps(resume.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n```\n")
    for name, text in texts.items():
        review_sections.append(f"## Fonte: {name}\n")
        review_sections.append("```\n" + text + "\n```\n")
    review_path.write_text("\n".join(review_sections), encoding="utf-8")

    print(f"Currículo escrito em {RESUME_PATH}")
    print(f"Relatório de revisão escrito em {review_path}")
    print("Revise o resultado antes de confiar nele como fonte da verdade.")


if __name__ == "__main__":
    main()
