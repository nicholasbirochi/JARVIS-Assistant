import pytest

from indexing import review
from indexing.proposals import Proposal, ProposedChange
from resume import store
from resume.schema import Bilingual, Evidence, PersonalInfo, Resume


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
    import config

    proposals_dir = tmp_path / "proposals"
    proposals_dir.mkdir()
    (proposals_dir / "proposal_20260101T000000Z.json").write_text("{}", encoding="utf-8")
    (proposals_dir / "proposal_20260202T000000Z.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "PROPOSALS_DIR", proposals_dir)

    result = review.latest_proposal_path()

    assert result is not None
    assert result.name == "proposal_20260202T000000Z.json"


def test_latest_proposal_path_none_when_missing(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "PROPOSALS_DIR", tmp_path / "does-not-exist")

    assert review.latest_proposal_path() is None


def test_pending_proposal_paths_ignores_reviewed_subfolder(tmp_path, monkeypatch):
    import config

    proposals_dir = tmp_path / "proposals"
    proposals_dir.mkdir()
    (proposals_dir / "proposal_20260101T000000Z.json").write_text("{}", encoding="utf-8")
    reviewed_dir = proposals_dir / "reviewed"
    reviewed_dir.mkdir()
    (reviewed_dir / "proposal_20251231T000000Z.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "PROPOSALS_DIR", proposals_dir)

    result = review.pending_proposal_paths()

    assert [p.name for p in result] == ["proposal_20260101T000000Z.json"]


def test_review_interactive_moves_proposal_to_reviewed_dir_when_given_a_path(seeded_resume, tmp_path, monkeypatch):
    import config

    proposals_dir = tmp_path / "proposals"
    proposals_dir.mkdir()
    proposal_path = proposals_dir / "proposal_20260101T000000Z.json"
    proposal_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "PROPOSALS_DIR", proposals_dir)

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

    review.review_interactive(proposal, proposal_path=proposal_path, input_func=lambda prompt: "a")

    assert not proposal_path.exists()
    assert (proposals_dir / "reviewed" / "proposal_20260101T000000Z.json").exists()
    assert review.pending_proposal_paths() == []


def test_review_interactive_does_not_move_anything_when_no_path_given(seeded_resume):
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

    # Should not raise just because there's no file to move (e.g. a
    # proposal built in-memory for a test, never written to disk).
    review.review_interactive(proposal, input_func=lambda prompt: "a")


def _write_proposal_file(path, n_changes: int) -> None:
    proposal = Proposal(
        created_at="2026-01-01T00:00:00Z",
        source_files=["/x.docx"],
        changes=[
            ProposedChange(
                kind="update_field",
                field_path="personal_info.phone",
                proposed_value=f"B{i}",
                existing_value="A",
                evidence=_evidence(),
            )
            for i in range(n_changes)
        ],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(proposal.model_dump_json(), encoding="utf-8")


def test_main_processes_every_pending_proposal_not_just_the_latest(seeded_resume, tmp_path, monkeypatch):
    # The real bug this guards against: a genuinely older, still-unreviewed
    # proposal was found sitting invisible on disk because main() used to
    # only ever look at the single most recent file.
    import config

    proposals_dir = tmp_path / "proposals"
    older = proposals_dir / "proposal_20260101T000000Z.json"
    newer = proposals_dir / "proposal_20260202T000000Z.json"
    _write_proposal_file(older, n_changes=1)
    _write_proposal_file(newer, n_changes=1)
    monkeypatch.setattr(config, "PROPOSALS_DIR", proposals_dir)

    answers = iter(["a", "a"])
    review.main(input_func=lambda prompt: next(answers))

    assert review.pending_proposal_paths() == []
    assert (proposals_dir / "reviewed" / older.name).exists()
    assert (proposals_dir / "reviewed" / newer.name).exists()


def test_main_reports_nothing_pending(capsys, tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "PROPOSALS_DIR", tmp_path / "proposals")

    review.main(input_func=lambda prompt: "a")

    assert "Nenhuma proposta pendente" in capsys.readouterr().out
