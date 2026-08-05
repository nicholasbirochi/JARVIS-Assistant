import pytest

from jarvis.indexing import review
from jarvis.indexing.proposals import Proposal, ProposedChange
from jarvis.resume import store
from jarvis.resume.schema import Bilingual, Evidence, PersonalInfo, Resume


def make_resume() -> Resume:
    return Resume(personal_info=PersonalInfo(full_name="Fulano", phone="A"), summary=Bilingual(pt="Resumo."))


@pytest.fixture
def seeded_resume(tmp_path, monkeypatch):
    path = tmp_path / "resume.json"
    monkeypatch.setattr(store, "RESUME_PATH", path)
    monkeypatch.setattr(store, "BACKUPS_DIR", tmp_path / "backups")
    store.save(make_resume())
    return path


def _evidence() -> list[Evidence]:
    return [Evidence(source_path="/x.docx", source_type="docx", read_at="2026-01-01T00:00:00Z")]


def test_accept_update_field_applies_and_saves(seeded_resume):
    proposal = Proposal(
        created_at="2026-01-01T00:00:00Z",
        source_files=["/x.docx"],
        changes=[
            ProposedChange(
                kind="update_field",
                field_path="personal_info.phone",
                proposed_value="B",
                existing_value="A",
                evidence=_evidence(),
            )
        ],
    )

    review.review_interactive(proposal, input_func=lambda prompt: "a")

    resume = store.load()
    assert resume.personal_info.phone == "B"
    assert resume.change_log[-1].source == "proposal_review"


def test_reject_does_not_apply(seeded_resume):
    proposal = Proposal(
        created_at="2026-01-01T00:00:00Z",
        source_files=["/x.docx"],
        changes=[
            ProposedChange(
                kind="update_field",
                field_path="personal_info.phone",
                proposed_value="B",
                existing_value="A",
                evidence=_evidence(),
            )
        ],
    )

    review.review_interactive(proposal, input_func=lambda prompt: "r")

    resume = store.load()
    assert resume.personal_info.phone == "A"


def test_skip_does_not_apply(seeded_resume):
    proposal = Proposal(
        created_at="2026-01-01T00:00:00Z",
        source_files=["/x.docx"],
        changes=[
            ProposedChange(
                kind="update_field",
                field_path="personal_info.phone",
                proposed_value="B",
                existing_value="A",
                evidence=_evidence(),
            )
        ],
    )

    review.review_interactive(proposal, input_func=lambda prompt: "p")

    resume = store.load()
    assert resume.personal_info.phone == "A"


def test_accept_new_item_appends_and_confirms_evidence(seeded_resume):
    proposal = Proposal(
        created_at="2026-01-01T00:00:00Z",
        source_files=["/x.pdf"],
        changes=[
            ProposedChange(
                kind="new_item",
                list_field="certifications",
                proposed_value={
                    "name": "Curso",
                    "status": "completed",
                    "evidence": [_evidence()[0].model_dump(mode="json")],
                },
                evidence=_evidence(),
            )
        ],
    )

    review.review_interactive(proposal, input_func=lambda prompt: "a")

    resume = store.load()
    assert len(resume.certifications) == 1
    assert resume.certifications[0].name == "Curso"
    assert resume.certifications[0].evidence[0].review_status == "confirmed"


def test_conflict_registered_regardless_of_decision(seeded_resume):
    proposal = Proposal(
        created_at="2026-01-01T00:00:00Z",
        source_files=["/x.docx"],
        changes=[
            ProposedChange(
                kind="update_field",
                field_path="personal_info.phone",
                proposed_value="B",
                existing_value="A",
                evidence=_evidence(),
                conflict=True,
            )
        ],
    )

    review.review_interactive(proposal, input_func=lambda prompt: "r")  # reject

    resume = store.load()
    assert len(resume.conflicts) == 1
    assert resume.conflicts[0].status == "resolved_existing"
    assert resume.personal_info.phone == "A"  # rejected -- not applied despite conflict logging


def test_conflict_accepted_records_resolved_proposed(seeded_resume):
    proposal = Proposal(
        created_at="2026-01-01T00:00:00Z",
        source_files=["/x.docx"],
        changes=[
            ProposedChange(
                kind="update_field",
                field_path="personal_info.phone",
                proposed_value="B",
                existing_value="A",
                evidence=_evidence(),
                conflict=True,
            )
        ],
    )

    review.review_interactive(proposal, input_func=lambda prompt: "a")

    resume = store.load()
    assert resume.conflicts[0].status == "resolved_proposed"
    assert resume.personal_info.phone == "B"


def test_latest_proposal_path_picks_most_recent(tmp_path, monkeypatch):
    from jarvis import config

    proposals_dir = tmp_path / "proposals"
    proposals_dir.mkdir()
    (proposals_dir / "proposal_20260101T000000Z.json").write_text("{}", encoding="utf-8")
    (proposals_dir / "proposal_20260202T000000Z.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "PROPOSALS_DIR", proposals_dir)

    result = review.latest_proposal_path()

    assert result is not None
    assert result.name == "proposal_20260202T000000Z.json"


def test_latest_proposal_path_none_when_missing(tmp_path, monkeypatch):
    from jarvis import config

    monkeypatch.setattr(config, "PROPOSALS_DIR", tmp_path / "does-not-exist")

    assert review.latest_proposal_path() is None
