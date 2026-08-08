import pytest

from jarvis.assistant import news
from jarvis.assistant.briefing import build_briefing
from jarvis.indexing.proposals import Proposal, ProposedChange
from jarvis.resume import store
from jarvis.resume.schema import Bilingual, Conflict, Evidence, PersonalInfo, Resume


@pytest.fixture(autouse=True)
def _no_real_news_by_default(monkeypatch):
    # build_briefing() also folds in news.build_news_briefing(), which
    # hits a real network endpoint -- never do that from ordinary unit
    # tests. Tests that specifically cover the news integration override
    # this explicitly.
    monkeypatch.setattr(news, "build_news_briefing", lambda: None)


def make_resume(**kwargs) -> Resume:
    return Resume(personal_info=PersonalInfo(full_name="Fulano", phone="A"), summary=Bilingual(pt="Resumo."), **kwargs)


def _evidence() -> list[Evidence]:
    return [Evidence(source_path="/x.docx", source_type="docx", read_at="2026-01-01T00:00:00Z")]


@pytest.fixture
def seeded_resume(tmp_path, monkeypatch):
    path = tmp_path / "resume.json"
    monkeypatch.setattr(store, "RESUME_PATH", path)
    monkeypatch.setattr(store, "BACKUPS_DIR", tmp_path / "backups")
    return path


@pytest.fixture
def empty_proposals_dir(tmp_path, monkeypatch):
    from jarvis import config

    proposals_dir = tmp_path / "proposals"
    monkeypatch.setattr(config, "PROPOSALS_DIR", proposals_dir)
    return proposals_dir


def _write_proposal(proposals_dir, name: str, n_changes: int) -> None:
    proposals_dir.mkdir(parents=True, exist_ok=True)
    changes = [
        ProposedChange(
            kind="update_field",
            field_path="personal_info.phone",
            proposed_value=f"B{i}",
            existing_value="A",
            evidence=_evidence(),
        )
        for i in range(n_changes)
    ]
    proposal = Proposal(created_at="2026-01-01T00:00:00Z", source_files=["/x.docx"], changes=changes)
    (proposals_dir / name).write_text(proposal.model_dump_json(), encoding="utf-8")


def test_build_briefing_returns_none_when_nothing_pending(seeded_resume, empty_proposals_dir):
    store.save(make_resume())

    assert build_briefing() is None


def test_build_briefing_mentions_singular_pending_change(seeded_resume, empty_proposals_dir):
    store.save(make_resume())
    _write_proposal(empty_proposals_dir, "proposal_20260101T000000Z.json", n_changes=1)

    briefing = build_briefing()

    assert briefing is not None
    assert "1 mudança de currículo pendente de revisão" in briefing


def test_build_briefing_mentions_plural_pending_changes_across_files(seeded_resume, empty_proposals_dir):
    store.save(make_resume())
    _write_proposal(empty_proposals_dir, "proposal_20260101T000000Z.json", n_changes=2)
    _write_proposal(empty_proposals_dir, "proposal_20260102T000000Z.json", n_changes=1)

    briefing = build_briefing()

    assert briefing is not None
    assert "3 mudanças de currículo pendentes de revisão" in briefing


def test_build_briefing_survives_an_unreadable_proposal_file(seeded_resume, empty_proposals_dir):
    # A malformed/corrupt proposal file must never take down the greeting --
    # a real legacy-schema proposal did exactly this before proposals.py
    # grew backward-compat coercion; this covers the case where a file is
    # simply not valid JSON/doesn't match the model at all.
    store.save(make_resume())
    empty_proposals_dir.mkdir(parents=True, exist_ok=True)
    (empty_proposals_dir / "proposal_20260101T000000Z.json").write_text("not json at all", encoding="utf-8")

    briefing = build_briefing()

    assert briefing is not None
    assert "1 proposta que não consegui ler" in briefing


def test_build_briefing_ignores_reviewed_proposals(seeded_resume, empty_proposals_dir):
    store.save(make_resume())
    _write_proposal(empty_proposals_dir / "reviewed", "proposal_20260101T000000Z.json", n_changes=5)

    assert build_briefing() is None


def test_build_briefing_mentions_open_conflicts(seeded_resume, empty_proposals_dir):
    resume = make_resume()
    resume.conflicts.append(
        Conflict(
            id="conflict-1",
            field_path="personal_info.phone",
            existing_value="A",
            proposed_value="B",
            sources=_evidence(),
            detected_at="2026-01-01T00:00:00Z",
            status="open",
        )
    )
    store.save(resume)

    briefing = build_briefing()

    assert briefing is not None
    assert "1 conflito em aberto no currículo" in briefing


def test_build_briefing_ignores_resolved_conflicts(seeded_resume, empty_proposals_dir):
    resume = make_resume()
    resume.conflicts.append(
        Conflict(
            id="conflict-1",
            field_path="personal_info.phone",
            existing_value="A",
            proposed_value="B",
            sources=_evidence(),
            detected_at="2026-01-01T00:00:00Z",
            status="resolved_proposed",
        )
    )
    store.save(resume)

    assert build_briefing() is None


def test_build_briefing_combines_both_kinds_of_pending_items(seeded_resume, empty_proposals_dir):
    resume = make_resume()
    resume.conflicts.append(
        Conflict(
            id="conflict-1",
            field_path="personal_info.phone",
            existing_value="A",
            proposed_value="B",
            sources=_evidence(),
            detected_at="2026-01-01T00:00:00Z",
            status="open",
        )
    )
    store.save(resume)
    _write_proposal(empty_proposals_dir, "proposal_20260101T000000Z.json", n_changes=1)

    briefing = build_briefing()

    assert briefing is not None
    assert "mudança de currículo pendente de revisão" in briefing
    assert "conflito em aberto no currículo" in briefing


def test_build_briefing_includes_news_when_available(seeded_resume, empty_proposals_dir, monkeypatch):
    store.save(make_resume())
    monkeypatch.setattr(news, "build_news_briefing", lambda: "Uma notícia de hoje: Teste.")

    briefing = build_briefing()

    assert briefing == "Uma notícia de hoje: Teste."


def test_build_briefing_combines_pending_items_and_news(seeded_resume, empty_proposals_dir, monkeypatch):
    store.save(make_resume())
    _write_proposal(empty_proposals_dir, "proposal_20260101T000000Z.json", n_changes=1)
    monkeypatch.setattr(news, "build_news_briefing", lambda: "Uma notícia de hoje: Teste.")

    briefing = build_briefing()

    assert "1 mudança de currículo pendente de revisão" in briefing
    assert "Uma notícia de hoje: Teste." in briefing


def test_build_briefing_still_none_when_nothing_pending_and_no_news(seeded_resume, empty_proposals_dir):
    store.save(make_resume())

    assert build_briefing() is None  # news mocked to None by the autouse fixture
