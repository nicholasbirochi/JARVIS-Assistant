from jarvis.indexing.proposals import (
    LLMProposalBatch,
    LLMProposedChange,
    Proposal,
    ProposedChange,
    UnreadableFile,
)
from jarvis.resume.schema import Evidence


def _make_evidence() -> list[Evidence]:
    return [
        Evidence(
            source_path="/x/cert.pdf",
            source_type="pdf",
            read_at="2026-01-01T00:00:00Z",
            snippet="trecho",
            confidence=0.9,
        )
    ]


def test_llm_proposed_change_round_trip():
    change = LLMProposedChange(kind="new_item", list_field="certifications", item={"name": "X"})
    restored = LLMProposedChange.model_validate(change.model_dump(mode="json"))
    assert restored == change


def test_llm_proposal_batch_round_trip():
    batch = LLMProposalBatch(changes=[LLMProposedChange(kind="update_field", field_path="personal_info.phone", value="123")])
    restored = LLMProposalBatch.model_validate(batch.model_dump(mode="json"))
    assert restored == batch


def test_proposed_change_conflict_default_false():
    change = ProposedChange(kind="update_field", field_path="x", proposed_value="y", evidence=_make_evidence())
    assert change.conflict is False


def test_proposed_change_accepts_legacy_single_evidence_dict():
    # Proposal files written before evidence became a list stored a single
    # Evidence dict here -- a real one from 2026-07-30 was found still
    # sitting on disk, unreadable, until this backward-compat coercion.
    single = _make_evidence()[0].model_dump(mode="json")
    change = ProposedChange.model_validate(
        {"kind": "update_field", "field_path": "x", "proposed_value": "y", "evidence": single}
    )
    assert change.evidence == [Evidence.model_validate(single)]


def test_proposed_change_still_accepts_evidence_list():
    change = ProposedChange.model_validate(
        {"kind": "update_field", "field_path": "x", "proposed_value": "y", "evidence": _make_evidence()}
    )
    assert change.evidence == _make_evidence()


def test_proposal_round_trip_with_unreadable_files():
    proposal = Proposal(
        created_at="2026-01-01T00:00:00Z",
        source_files=["/x/a.docx"],
        changes=[ProposedChange(kind="update_field", field_path="x", proposed_value="y", evidence=_make_evidence())],
        unreadable_files=[UnreadableFile(path="/x/b.pdf", reason="sem texto", detected_at="2026-01-01T00:00:00Z")],
    )
    restored = Proposal.model_validate(proposal.model_dump(mode="json"))
    assert restored == proposal


# LLMProposedChange.item is a deliberate, documented exception (see
# proposals.py) -- its shape genuinely varies by the sibling "list_field"
# value, which JSON-schema can't express as a fixed properties list without
# a discriminated union local structured-output decoding doesn't enforce
# well anyway.
_ALLOWED_OPEN_PATHS = {"$defs.LLMProposedChange.item"}


def _assert_additional_properties_false(schema, path="$"):
    if not isinstance(schema, dict):
        return
    if (schema.get("type") == "object" or "properties" in schema) and path not in _ALLOWED_OPEN_PATHS:
        assert schema.get("additionalProperties") is False, f"{path} missing additionalProperties:false"
    for name, sub in schema.get("properties", {}).items():
        _assert_additional_properties_false(sub, f"{path}.{name}")
    if "items" in schema:
        _assert_additional_properties_false(schema["items"], f"{path}[]")
    for key in ("anyOf", "allOf", "oneOf"):
        for i, sub in enumerate(schema.get(key, [])):
            _assert_additional_properties_false(sub, f"{path}.{key}[{i}]")


def test_llm_proposal_batch_schema_forbids_additional_properties():
    schema = LLMProposalBatch.model_json_schema()
    for name, definition in schema.get("$defs", {}).items():
        _assert_additional_properties_false(definition, f"$defs.{name}")
    _assert_additional_properties_false(schema, "$root")
