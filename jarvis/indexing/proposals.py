"""Pydantic models for the indexer's output. `Proposal` is the on-disk
artifact (data/proposals/proposal_<stamp>.json) -- it is never auto-applied
to data/resume.json; jarvis/indexing/review.py is the only thing that turns
a ProposedChange into an actual store.update_field/append_item call.

LLMProposalBatch/LLMProposedChange are deliberately smaller and separate --
they're what's actually sent to/from the model. Asking the model to also
emit evidence/conflict (which are code-derived, see schema.py's docstring)
would be both unnecessary and an invitation for it to hallucinate a path or
timestamp.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import Field

from jarvis.resume.schema import Evidence, StrictModel


class LLMProposedChange(StrictModel):
    kind: Literal["update_field", "new_item"]
    field_path: Optional[str] = None
    list_field: Optional[str] = None
    # kind="update_field": the new value, ALWAYS as a string (JSON-encode
    # non-string values, e.g. "true", "42", '["a", "b"]'). A concrete
    # `string` JSON-schema type is what actually gets the local model to
    # reliably fill this in -- an unconstrained `Any` field was empirically
    # observed to come back null even when quote/rationale were correct.
    value: str = ""
    # kind="new_item": the new list entry's fields, matching that list's item
    # shape (Certification/Project/Experience/... -- whichever "list_field"
    # names). Deliberately left as an open dict rather than a discriminated
    # union of all five item schemas: the target shape depends on a sibling
    # field's value, which local structured-output decoding doesn't enforce
    # well via JSON-schema conditionals anyway, and empirically this open
    # form is filled in correctly (unlike the unconstrained scalar case
    # `value` replaced above). This is the one field exempted from the
    # additionalProperties:false rule enforced everywhere else.
    item: dict[str, Any] = Field(default_factory=dict)
    quote: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    rationale: Optional[str] = None


class LLMProposalBatch(StrictModel):
    changes: list[LLMProposedChange] = Field(default_factory=list)


class ProposedChange(StrictModel):
    kind: Literal["update_field", "new_item"]
    field_path: Optional[str] = None
    list_field: Optional[str] = None
    proposed_value: Any = None
    existing_value: Any = None
    # A list, not one Evidence: the same fact commonly shows up in several
    # source files (e.g. a "Brasil" and an "International" résumé variant
    # both mentioning the same phone number) -- runner.py's dedupe step
    # merges those into one change backed by every corroborating source,
    # instead of asking the reviewer to accept the same fact N times.
    evidence: list[Evidence] = Field(default_factory=list)
    conflict: bool = False
    rationale: Optional[str] = None


class UnreadableFile(StrictModel):
    path: str
    reason: str
    detected_at: str


class Proposal(StrictModel):
    created_at: str
    source_files: list[str] = Field(default_factory=list)
    changes: list[ProposedChange] = Field(default_factory=list)
    unreadable_files: list[UnreadableFile] = Field(default_factory=list)
