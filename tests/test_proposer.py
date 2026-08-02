from pathlib import Path

from jarvis.indexing import proposer
from jarvis.indexing.proposals import LLMProposalBatch, LLMProposedChange
from jarvis.resume.schema import Bilingual, PersonalInfo, Resume


def make_resume() -> Resume:
    return Resume(
        personal_info=PersonalInfo(full_name="Nicholas Birochi", phone="+55 11 90000-0000"),
        summary=Bilingual(pt="Resumo."),
    )


def test_attach_evidence_detects_conflict_on_differing_value(tmp_path):
    resume = make_resume()
    batch = LLMProposalBatch(
        changes=[
            LLMProposedChange(
                kind="update_field",
                field_path="personal_info.phone",
                value="+55 11 99999-9999",
                quote="telefone: (11) 99999-9999",
                confidence=0.8,
            )
        ]
    )
    path = tmp_path / "cert.pdf"

    changes = proposer.attach_evidence(batch, path, resume)

    assert len(changes) == 1
    assert changes[0].conflict is True
    assert changes[0].existing_value == "+55 11 90000-0000"
    assert changes[0].evidence.confidence == 0.8
    assert changes[0].evidence.snippet == "telefone: (11) 99999-9999"


def test_attach_evidence_no_conflict_when_value_matches(tmp_path):
    resume = make_resume()
    batch = LLMProposalBatch(
        changes=[
            LLMProposedChange(
                kind="update_field", field_path="personal_info.phone", value="+55 11 90000-0000"
            )
        ]
    )

    changes = proposer.attach_evidence(batch, tmp_path / "x.docx", resume)

    assert changes[0].conflict is False


def test_attach_evidence_bad_field_path_yields_none_existing_value(tmp_path):
    resume = make_resume()
    batch = LLMProposalBatch(
        changes=[
            LLMProposedChange(kind="update_field", field_path="not.a.real.path", value="x")
        ]
    )

    changes = proposer.attach_evidence(batch, tmp_path / "x.docx", resume)

    assert changes[0].existing_value is None
    assert changes[0].conflict is False


def test_attach_evidence_new_item_embeds_evidence_in_proposed_value(tmp_path):
    resume = make_resume()
    batch = LLMProposalBatch(
        changes=[
            LLMProposedChange(
                kind="new_item",
                list_field="certifications",
                item={"name": "Curso X", "status": "completed"},
            )
        ]
    )

    changes = proposer.attach_evidence(batch, tmp_path / "cert.pdf", resume)

    assert changes[0].proposed_value["name"] == "Curso X"
    assert len(changes[0].proposed_value["evidence"]) == 1
    assert changes[0].conflict is False


def test_attach_evidence_coerces_json_string_value_to_real_type(tmp_path):
    resume = make_resume()
    batch = LLMProposalBatch(
        changes=[LLMProposedChange(kind="update_field", field_path="experience", value="[]")]
    )

    changes = proposer.attach_evidence(batch, tmp_path / "x.docx", resume)

    assert changes[0].proposed_value == []


def test_attach_evidence_normalizes_bracket_notation_field_path(tmp_path):
    resume = make_resume()
    bracket_batch = LLMProposalBatch(
        changes=[LLMProposedChange(kind="update_field", field_path="certifications[0].hours", value="10")]
    )

    changes = proposer.attach_evidence(bracket_batch, tmp_path / "x.docx", resume)

    assert changes[0].field_path == "certifications.0.hours"


class FakeProvider:
    def __init__(self, result: dict):
        self._result = result
        self.calls: list[dict] = []

    def structured_chat(self, messages, json_schema):
        self.calls.append({"messages": messages, "json_schema": json_schema})
        return self._result

    def chat(self, messages, tool_specs):  # pragma: no cover - not used here
        raise NotImplementedError


def test_propose_changes_for_file_calls_provider_with_batch_schema(tmp_path, monkeypatch):
    fake_provider = FakeProvider({"changes": []})
    monkeypatch.setattr(proposer, "get_provider", lambda: fake_provider)

    resume = make_resume()
    result = proposer.propose_changes_for_file(Path("/x/cert.pdf"), "algum texto", resume)

    assert isinstance(result, LLMProposalBatch)
    assert result.changes == []
    assert len(fake_provider.calls) == 1
    assert fake_provider.calls[0]["json_schema"] == LLMProposalBatch.model_json_schema()
