import unicodedata

import config
from indexing import scanner


def test_normalize_path_key_collapses_nfd_and_nfc(tmp_path):
    # Build a real file whose name contains an accented character, then
    # construct two Path objects pointing at it -- one via an NFD-encoded
    # string, one via NFC -- exactly the gotcha confirmed on this Mac
    # (the real "Currículos" folder is stored NFD on disk).
    name_nfc = unicodedata.normalize("NFC", "café.txt")
    name_nfd = unicodedata.normalize("NFD", "café.txt")
    real_file = tmp_path / name_nfc
    real_file.write_text("conteúdo", encoding="utf-8")

    key_from_nfc = scanner.normalize_path_key(tmp_path / name_nfc)
    key_from_nfd = scanner.normalize_path_key(tmp_path / name_nfd)

    assert key_from_nfc == key_from_nfd


def test_iter_candidate_files_filters_extensions_and_excluded_paths(tmp_path, monkeypatch):
    root = tmp_path / "root"
    excluded = root / "excluded_project"
    excluded.mkdir(parents=True)
    (root / "resume.docx").write_text("x", encoding="utf-8")
    (root / "cert.pdf").write_text("x", encoding="utf-8")
    (root / "notes.md").write_text("x", encoding="utf-8")
    (root / "photo.jpg").write_text("x", encoding="utf-8")
    (excluded / "readme.md").write_text("x", encoding="utf-8")

    monkeypatch.setattr(config, "AUTHORIZED_INDEX_ROOTS", [root])
    monkeypatch.setattr(config, "EXCLUDED_INDEX_PATHS", [excluded])

    files = {p.name for p in scanner.iter_candidate_files()}

    assert files == {"resume.docx", "cert.pdf", "notes.md"}


def test_iter_candidate_files_prunes_vendor_and_build_noise(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "node_modules" / "some-pkg").mkdir(parents=True)
    (root / "node_modules" / "some-pkg" / "README.md").write_text("x", encoding="utf-8")
    (root / "obj" / "Debug").mkdir(parents=True)
    (root / "obj" / "Debug" / "notes.txt").write_text("x", encoding="utf-8")
    (root / "real_project").mkdir(parents=True)
    (root / "real_project" / "README.md").write_text("x", encoding="utf-8")

    monkeypatch.setattr(config, "AUTHORIZED_INDEX_ROOTS", [root])
    monkeypatch.setattr(config, "EXCLUDED_INDEX_PATHS", [])

    files = {p.relative_to(root).as_posix() for p in scanner.iter_candidate_files()}

    assert files == {"real_project/README.md"}


def test_iter_candidate_files_tolerates_missing_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUTHORIZED_INDEX_ROOTS", [tmp_path / "does-not-exist"])
    monkeypatch.setattr(config, "EXCLUDED_INDEX_PATHS", [])

    assert scanner.iter_candidate_files() == []


def test_diff_against_state_detects_new_and_changed_files(tmp_path):
    file_a = tmp_path / "a.txt"
    file_a.write_text("v1", encoding="utf-8")

    state = {}
    changed = scanner.diff_against_state([file_a], state)
    assert changed == [file_a]

    # simulate having already processed it
    state[scanner.normalize_path_key(file_a)] = scanner.FileRecord(
        hash=scanner.file_hash(file_a), size=file_a.stat().st_size, mtime=file_a.stat().st_mtime, last_processed_at="x"
    )
    assert scanner.diff_against_state([file_a], state) == []

    file_a.write_text("v2", encoding="utf-8")
    assert scanner.diff_against_state([file_a], state) == [file_a]


def test_diff_against_state_treats_hash_failure_as_needing_processing(tmp_path, monkeypatch):
    # Simulates a OneDrive placeholder file that isn't locally materialized
    # yet -- reading it raises TimeoutError (an OSError subclass) instead of
    # succeeding. diff_against_state must not crash the whole scan over it.
    file_a = tmp_path / "a.txt"
    file_a.write_text("v1", encoding="utf-8")

    def failing_hash(path):
        raise TimeoutError(60, "Operation timed out")

    monkeypatch.setattr(scanner, "file_hash", failing_hash)

    changed = scanner.diff_against_state([file_a], {})

    assert changed == [file_a]


def test_index_state_round_trip(tmp_path):
    state_path = tmp_path / "index_state.json"
    record = scanner.FileRecord(hash="abc", size=10, mtime=123.0, last_processed_at="2026-01-01T00:00:00Z")
    scanner.save_index_state(state_path, {"key1": record})

    loaded = scanner.load_index_state(state_path)

    assert loaded == {"key1": record}


def test_load_index_state_missing_file_returns_empty_dict(tmp_path):
    assert scanner.load_index_state(tmp_path / "nope.json") == {}
