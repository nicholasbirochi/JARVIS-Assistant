import json

import config
from indexing import runner
from indexing.proposals import LLMProposalBatch, LLMProposedChange
from resume.schema import Bilingual, PersonalInfo, Resume
from indexing import proposer


def make_resume() -> Resume:
    return Resume(personal_info=PersonalInfo(full_name="Fulano"), summary=Bilingual(pt="Resumo."))


def _setup_authorized_root(tmp_path):
    root = tmp_path / "authorized"
    root.mkdir()
    (root / "cert.txt").write_text("Certificado de Python concluído em 2026.", encoding="utf-8")
    return root


def test_run_writes_proposal_and_updates_index_state(tmp_path, monkeypatch):
    root = _setup_authorized_root(tmp_path)
    monkeypatch.setattr(config, "AUTHORIZED_INDEX_ROOTS", [root])
    monkeypatch.setattr(config, "EXCLUDED_INDEX_PATHS", [])
    monkeypatch.setattr(config, "INDEX_STATE_PATH", tmp_path / "index_state.json")
    monkeypatch.setattr(config, "PROPOSALS_DIR", tmp_path / "proposals")

    fake_batch = LLMProposalBatch(
        changes=[
            LLMProposedChange(
                kind="new_item",
                list_field="certifications",
                item={"name": "Python", "status": "completed"},
                quote="Certificado de Python",
                confidence=0.9,
            )
        ]
    )
    monkeypatch.setattr(proposer, "propose_changes_for_file", lambda path, text, resume: fake_batch)

    result_path = runner.run(resume=make_resume())

    assert result_path is not None
    assert result_path.exists()
    data = json.loads(result_path.read_text(encoding="utf-8"))
    assert len(data["changes"]) == 1
    assert data["changes"][0]["proposed_value"]["name"] == "Python"

    state_path = tmp_path / "index_state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(state) == 1


def test_run_second_pass_with_no_changes_returns_none(tmp_path, monkeypatch):
    root = _setup_authorized_root(tmp_path)
    monkeypatch.setattr(config, "AUTHORIZED_INDEX_ROOTS", [root])
    monkeypatch.setattr(config, "EXCLUDED_INDEX_PATHS", [])
    monkeypatch.setattr(config, "INDEX_STATE_PATH", tmp_path / "index_state.json")
    monkeypatch.setattr(config, "PROPOSALS_DIR", tmp_path / "proposals")
    monkeypatch.setattr(
        proposer, "propose_changes_for_file", lambda path, text, resume: LLMProposalBatch(changes=[])
    )

    first = runner.run(resume=make_resume())
    assert first is not None

    second = runner.run(resume=make_resume())
    assert second is None


def test_run_handles_unreadable_file_without_crashing(tmp_path, monkeypatch):
    root = tmp_path / "authorized"
    root.mkdir()
    (root / "photo.pdf").write_bytes(b"%PDF-not-real")
    monkeypatch.setattr(config, "AUTHORIZED_INDEX_ROOTS", [root])
    monkeypatch.setattr(config, "EXCLUDED_INDEX_PATHS", [])
    monkeypatch.setattr(config, "INDEX_STATE_PATH", tmp_path / "index_state.json")
    monkeypatch.setattr(config, "PROPOSALS_DIR", tmp_path / "proposals")

    result_path = runner.run(resume=make_resume())

    assert result_path is not None
    data = json.loads(result_path.read_text(encoding="utf-8"))
    assert data["changes"] == []
    assert len(data["unreadable_files"]) == 1


def test_run_handles_hash_timeout_after_successful_extraction(tmp_path, monkeypatch):
    # A file whose text was readable but that then times out when hashed for
    # index-state bookkeeping (e.g. OneDrive dehydrated mid-run) must not
    # crash the run, and must not be marked processed (so it's retried).
    root = _setup_authorized_root(tmp_path)
    monkeypatch.setattr(config, "AUTHORIZED_INDEX_ROOTS", [root])
    monkeypatch.setattr(config, "EXCLUDED_INDEX_PATHS", [])
    monkeypatch.setattr(config, "INDEX_STATE_PATH", tmp_path / "index_state.json")
    monkeypatch.setattr(config, "PROPOSALS_DIR", tmp_path / "proposals")
    monkeypatch.setattr(
        proposer, "propose_changes_for_file", lambda path, text, resume: LLMProposalBatch(changes=[])
    )

    from indexing import scanner as scanner_module

    def failing_hash(path):
        raise TimeoutError(60, "Operation timed out")

    monkeypatch.setattr(scanner_module, "file_hash", failing_hash)

    result_path = runner.run(resume=make_resume())

    assert result_path is not None
    data = json.loads(result_path.read_text(encoding="utf-8"))
    assert len(data["unreadable_files"]) == 1

    state = json.loads((tmp_path / "index_state.json").read_text(encoding="utf-8"))
    assert state == {}  # never marked processed -- will be retried next run


def test_run_retries_file_that_failed_to_read_instead_of_marking_no_text(tmp_path, monkeypatch):
    # extract.extract_text raising OSError (OneDrive placeholder timeout,
    # etc.) must not be recorded as a permanent "no text" verdict, and the
    # file must not be marked processed in index_state -- so it's picked
    # up again on the next run once the file is actually readable.
    root = _setup_authorized_root(tmp_path)
    monkeypatch.setattr(config, "AUTHORIZED_INDEX_ROOTS", [root])
    monkeypatch.setattr(config, "EXCLUDED_INDEX_PATHS", [])
    monkeypatch.setattr(config, "INDEX_STATE_PATH", tmp_path / "index_state.json")
    monkeypatch.setattr(config, "PROPOSALS_DIR", tmp_path / "proposals")

    from indexing import extract as extract_module

    def failing_extract(path):
        raise TimeoutError(60, "Operation timed out")

    monkeypatch.setattr(extract_module, "extract_text", failing_extract)

    result_path = runner.run(resume=make_resume())

    assert result_path is not None
    data = json.loads(result_path.read_text(encoding="utf-8"))
    assert data["changes"] == []
    assert len(data["unreadable_files"]) == 1
    assert "tentar novamente" in data["unreadable_files"][0]["reason"]

    state = json.loads((tmp_path / "index_state.json").read_text(encoding="utf-8"))
    assert state == {}  # never marked processed -- will be retried next run


def test_run_respects_limit(tmp_path, monkeypatch):
    root = tmp_path / "authorized"
    root.mkdir()
    for i in range(5):
        (root / f"note{i}.txt").write_text(f"conteúdo {i}", encoding="utf-8")
    monkeypatch.setattr(config, "AUTHORIZED_INDEX_ROOTS", [root])
    monkeypatch.setattr(config, "EXCLUDED_INDEX_PATHS", [])
    monkeypatch.setattr(config, "INDEX_STATE_PATH", tmp_path / "index_state.json")
    monkeypatch.setattr(config, "PROPOSALS_DIR", tmp_path / "proposals")
    monkeypatch.setattr(
        proposer, "propose_changes_for_file", lambda path, text, resume: LLMProposalBatch(changes=[])
    )

    result_path = runner.run(resume=make_resume(), limit=2)

    data = json.loads(result_path.read_text(encoding="utf-8"))
    assert len(data["source_files"]) == 2
