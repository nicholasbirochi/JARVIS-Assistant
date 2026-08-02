"""Interactive review of a proposal file -- the only place a ProposedChange
actually reaches data/resume.json. Conflicts are registered regardless of
the reviewer's decision (accept/reject/skip): "two sources disagreed and a
human looked at it" is itself audit-worthy, independent of the outcome."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from jarvis.indexing.proposals import Proposal, ProposedChange
from jarvis.resume import store
from jarvis.resume.schema import Conflict


def latest_proposal_path() -> Path | None:
    from jarvis.config import PROPOSALS_DIR  # live lookup -- monkeypatchable in tests

    if not PROPOSALS_DIR.exists():
        return None
    candidates = sorted(PROPOSALS_DIR.glob("proposal_*.json"))
    return candidates[-1] if candidates else None


def load_proposal(path: Path) -> Proposal:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Proposal.model_validate(data)


def _print_change(change: ProposedChange, index: int, total: int) -> None:
    print(f"\n[{index}/{total}] {change.kind}")
    if change.field_path:
        print(f"  campo: {change.field_path}")
    if change.list_field:
        print(f"  lista: {change.list_field}")
    print(f"  valor atual: {change.existing_value!r}")
    print(f"  valor proposto: {change.proposed_value!r}")
    if change.conflict:
        print("  ATENÇÃO: conflita com o valor atual registrado.")
    print(f"  fonte: {change.evidence.source_path}")
    if change.evidence.snippet:
        print(f"  trecho: \"{change.evidence.snippet}\"")
    if change.rationale:
        print(f"  motivo: {change.rationale}")


def review_interactive(proposal: Proposal, input_func=input) -> None:
    resume = store.load()

    for i, change in enumerate(proposal.changes, start=1):
        _print_change(change, i, len(proposal.changes))
        answer = input_func("  aceitar / rejeitar / pular? [a/r/p] ").strip().lower()
        accepted = answer.startswith("a")
        mutated = False

        # Registered regardless of the decision below -- "two sources
        # disagreed and a human looked at it" is audit-worthy on its own,
        # so this must be saved even if the change itself is rejected/skipped.
        if change.conflict:
            resolved_status = (
                "resolved_proposed" if accepted else "resolved_existing" if answer.startswith("r") else "open"
            )
            resume = store.register_conflict(
                resume,
                Conflict(
                    id=f"conflict-{uuid4().hex[:8]}",
                    field_path=change.field_path or f"{change.list_field}.new",
                    existing_value=change.existing_value,
                    proposed_value=change.proposed_value,
                    sources=[change.evidence],
                    detected_at=datetime.now(timezone.utc).isoformat(),
                    status=resolved_status,
                ),
            )
            mutated = True

        if accepted:
            try:
                if change.kind == "update_field" and change.field_path:
                    resume = store.update_field(
                        resume,
                        change.field_path,
                        change.proposed_value,
                        source="proposal_review",
                        note=change.rationale,
                    )
                    mutated = True
                elif change.kind == "new_item" and change.list_field:
                    item = dict(change.proposed_value) if isinstance(change.proposed_value, dict) else {}
                    if item.get("evidence"):
                        item["evidence"][0]["review_status"] = "confirmed"
                    resume = store.append_item(
                        resume, change.list_field, item, source="proposal_review", note=change.rationale
                    )
                    mutated = True
                else:
                    print("  ERRO: mudança mal-formada -- pulando.")
            except (store.FieldPathError, ValidationError) as exc:
                print(f"  ERRO ao aplicar: {exc} -- pulando.")

        if mutated:
            store.save(resume)
            if accepted:
                print("  aplicado.")


def main() -> None:
    path = latest_proposal_path()
    if path is None:
        print("Nenhuma proposta encontrada em data/proposals/. Rode `python -m jarvis index` primeiro.")
        return
    print(f"Revisando {path.name}")
    review_interactive(load_proposal(path))


if __name__ == "__main__":
    main()
