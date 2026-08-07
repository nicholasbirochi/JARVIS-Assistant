"""Proactive briefing spoken right after the greeting, when there's
something pending JARVIS already knows about -- so you don't have to
remember to run `review-proposals` or notice a conflict yourself.

Deliberately built entirely from code-derived facts (counting files/records
already on disk), never from the LLM -- the whole point is a short, factual
heads-up, and letting a model "summarize" this would reopen exactly the kind
of ungrounded-claim risk jarvis/indexing/proposer.py's _is_grounded() exists
to prevent. If nothing is pending, returns None and nothing extra is said,
matching the "fala só o necessário" principle.

Gupy session status is deliberately NOT checked here -- check_session()
opens a real (headless) browser and navigates a live page, which costs
real seconds; doing that on every single activation would make greeting
JARVIS noticeably slower for a check that's rarely actionable in the
moment. Left for a later, explicitly-throttled version if it's wanted.
"""

from __future__ import annotations

from jarvis.indexing import review
from jarvis.resume import store


def build_briefing() -> str | None:
    parts: list[str] = []

    pending = review.pending_proposal_paths()
    if pending:
        total_changes = 0
        unreadable = 0
        for p in pending:
            try:
                total_changes += len(review.load_proposal(p).changes)
            except Exception:
                # A malformed/corrupt proposal file must never take down the
                # whole greeting -- report it as its own item instead (still
                # actionable: `review-proposals` will surface the real error).
                unreadable += 1
        if total_changes == 1:
            parts.append("1 mudança de currículo pendente de revisão")
        elif total_changes > 1:
            parts.append(f"{total_changes} mudanças de currículo pendentes de revisão")
        if unreadable == 1:
            parts.append("1 proposta que não consegui ler")
        elif unreadable > 1:
            parts.append(f"{unreadable} propostas que não consegui ler")

    resume = store.load()
    open_conflicts = [c for c in resume.conflicts if c.status == "open"]
    if len(open_conflicts) == 1:
        parts.append("1 conflito em aberto no currículo")
    elif len(open_conflicts) > 1:
        parts.append(f"{len(open_conflicts)} conflitos em aberto no currículo")

    if not parts:
        return None
    return "Antes de começarmos: você tem " + " e ".join(parts) + "."
