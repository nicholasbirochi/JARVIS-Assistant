import pytest
from pydantic import ValidationError

from jarvis.resume.schema import (
    ChangeRecord,
    Conflict,
    Evidence,
    PersonalInfo,
    Resume,
)


def _minimal_resume_v1_dict() -> dict:
    """A resume shaped like the pre-v2 schema -- no evidence/conflicts/
    change_log/availability keys at all."""
    return {
        "personal_info": {"full_name": "Fulano de Tal"},
        "summary": {"pt": "Resumo."},
        "experience": [
            {
                "id": "exp-1",
                "title": {"pt": "Cargo"},
                "company": "Empresa",
            }
        ],
    }


def test_old_shaped_dict_still_validates_with_v2_defaults():
    resume = Resume.model_validate(_minimal_resume_v1_dict())

    assert resume.conflicts == []
    assert resume.change_log == []
    assert resume.experience[0].evidence == []
    assert resume.personal_info.evidence == []
    assert resume.job_preferences.availability.status == "unspecified"


def test_evidence_confidence_bounds():
    Evidence(source_path="/x", source_type="docx", read_at="2026-01-01T00:00:00Z", confidence=0.0)
    Evidence(source_path="/x", source_type="docx", read_at="2026-01-01T00:00:00Z", confidence=1.0)

    with pytest.raises(ValidationError):
        Evidence(source_path="/x", source_type="docx", read_at="2026-01-01T00:00:00Z", confidence=1.5)
    with pytest.raises(ValidationError):
        Evidence(source_path="/x", source_type="docx", read_at="2026-01-01T00:00:00Z", confidence=-0.1)


def test_conflict_round_trip():
    conflict = Conflict(
        id="c1",
        field_path="personal_info.phone",
        existing_value="+55 11 90000-0000",
        proposed_value="+55 11 91111-1111",
        detected_at="2026-01-01T00:00:00Z",
    )
    restored = Conflict.model_validate(conflict.model_dump(mode="json"))
    assert restored == conflict


def test_change_record_round_trip():
    record = ChangeRecord(
        timestamp="2026-01-01T00:00:00Z",
        field_path="personal_info.phone",
        old_value="A",
        new_value="B",
        source="voice",
    )
    restored = ChangeRecord.model_validate(record.model_dump(mode="json"))
    assert restored == record


def _assert_additional_properties_false(schema, path="$"):
    if not isinstance(schema, dict):
        return
    if schema.get("type") == "object" or "properties" in schema:
        assert schema.get("additionalProperties") is False, f"{path} missing additionalProperties:false"
    for name, sub in schema.get("properties", {}).items():
        _assert_additional_properties_false(sub, f"{path}.{name}")
    if "items" in schema:
        _assert_additional_properties_false(schema["items"], f"{path}[]")
    for key in ("anyOf", "allOf", "oneOf"):
        for i, sub in enumerate(schema.get(key, [])):
            _assert_additional_properties_false(sub, f"{path}.{key}[{i}]")


def test_every_object_subschema_forbids_additional_properties():
    full_schema = Resume.model_json_schema()
    for name, definition in full_schema.get("$defs", {}).items():
        _assert_additional_properties_false(definition, f"$defs.{name}")
    _assert_additional_properties_false(full_schema, "$root")


def test_personal_info_evidence_field_exists():
    info = PersonalInfo(full_name="X", evidence=[
        Evidence(source_path="/a.docx", source_type="docx", read_at="2026-01-01T00:00:00Z")
    ])
    assert len(info.evidence) == 1
