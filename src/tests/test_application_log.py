import config
from sites import application_log


def test_load_applications_log_empty_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    assert application_log.load_applications_log() == {}


def test_load_applications_log_returns_empty_on_malformed_json(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    application_log.applications_log_path().write_text("not valid json{{{", encoding="utf-8")

    assert application_log.load_applications_log() == {}


def test_record_application_persists_across_reloads(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    application_log.record_application("https://empresa.gupy.io/job/abc", "gupy")

    log = application_log.load_applications_log()
    assert "https://empresa.gupy.io/job/abc" in log
    assert log["https://empresa.gupy.io/job/abc"]["site_name"] == "gupy"
    assert "submitted_at" in log["https://empresa.gupy.io/job/abc"]


def test_record_application_creates_the_data_dir_if_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "does" / "not" / "exist" / "yet")

    application_log.record_application("https://empresa.gupy.io/job/abc", "gupy")

    assert application_log.applications_log_path().exists()


def test_record_application_defaults_source_to_jarvis(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    application_log.record_application("https://empresa.gupy.io/job/abc", "gupy")

    log = application_log.load_applications_log()
    assert log["https://empresa.gupy.io/job/abc"]["source"] == "jarvis"


def test_record_application_accepts_a_manual_source(monkeypatch, tmp_path):
    # 2026-09-07, "me candidatei a todas as vagas de banco e as
    # Fintechs!" -- Nicholas applying by hand, outside any automated
    # flow, is just as real a submission and must be recordable too.
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    application_log.record_application("https://empresa.gupy.io/job/abc", "gupy", source="manual")

    log = application_log.load_applications_log()
    assert log["https://empresa.gupy.io/job/abc"]["source"] == "manual"


def test_record_application_overwrites_a_prior_entry_for_the_same_url(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    application_log.record_application("https://empresa.gupy.io/job/abc", "gupy")
    first = application_log.load_applications_log()["https://empresa.gupy.io/job/abc"]["submitted_at"]

    application_log.record_application("https://empresa.gupy.io/job/abc", "gupy")
    second = application_log.load_applications_log()["https://empresa.gupy.io/job/abc"]["submitted_at"]

    # Same key, freshly re-written -- not asserting the two timestamps
    # differ (they may land in the same instant on a fast machine), just
    # that a second real record_application() doesn't crash or duplicate
    # the entry into some other shape.
    assert len(application_log.load_applications_log()) == 1
    assert first and second
