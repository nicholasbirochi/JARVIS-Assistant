from jarvis import config
from jarvis.job_search import latest_report_path, run_job_search, save_report, summarize
from jarvis.resume.schema import Bilingual, PersonalInfo, Resume
from jarvis.sites.base import JobListing


def make_resume() -> Resume:
    return Resume(
        personal_info=PersonalInfo(full_name="Nicholas Birochi", phone=None, email="n@example.com"),
        summary=Bilingual(pt="Resumo."),
    )


class FakeAdapter:
    def __init__(self, listings: list[JobListing] | None = None, *, fail: bool = False):
        self._listings = listings or []
        self._fail = fail
        self.calls: list[str] = []

    def search_jobs(self, query: str, *, max_results: int = 20) -> list[JobListing]:
        self.calls.append(query)
        if self._fail:
            raise RuntimeError("site indisponível")
        return self._listings


def make_listing(external_id, title, *, site_name="infojobs", location="São Paulo - SP", snippet=None) -> JobListing:
    return JobListing(
        site_name=site_name,
        external_id=external_id,
        title=title,
        company="Empresa",
        location=location,
        url=f"https://example.com/{site_name}/{external_id}",
        snippet=snippet,
    )


def test_run_job_search_splits_local_and_remote():
    local_listing = make_listing("1", "Analista De Dados", location="São Bernardo do Campo - SP")
    remote_listing = make_listing("2", "Analista De Dados", location=None, snippet="100% remoto")
    adapters = {"infojobs": FakeAdapter([local_listing, remote_listing])}

    report = run_job_search(make_resume(), adapters=adapters)

    assert [listing.external_id for listing in report.local] == ["1"]
    assert [listing.external_id for listing in report.remote] == ["2"]
    assert report.sites_searched == ["infojobs"]
    assert report.sites_failed == {}


def test_run_job_search_records_a_failing_site_without_losing_the_others():
    good_listing = make_listing("1", "Analista De Dados", location="São Paulo - SP", site_name="catho")
    adapters = {
        "infojobs": FakeAdapter(fail=True),
        "catho": FakeAdapter([good_listing]),
    }

    report = run_job_search(make_resume(), adapters=adapters)

    assert report.sites_searched == ["catho"]
    assert "infojobs" in report.sites_failed
    assert len(report.local) == 1


def test_run_job_search_caps_the_number_of_terms_queried():
    adapter = FakeAdapter([])
    adapters = {"infojobs": adapter}

    run_job_search(make_resume(), adapters=adapters)

    from jarvis.job_search import _MAX_TERMS

    assert len(adapter.calls) == _MAX_TERMS


def test_save_report_and_latest_report_path_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    local_listing = make_listing("1", "Analista De Dados", location="São Bernardo do Campo - SP")
    adapters = {"infojobs": FakeAdapter([local_listing])}
    report = run_job_search(make_resume(), adapters=adapters)

    path = save_report(report)

    assert latest_report_path() is not None
    assert str(latest_report_path()) == path
    content = latest_report_path().read_text(encoding="utf-8")
    assert "Analista De Dados" in content
    assert "São Bernardo do Campo" in content


def test_latest_report_path_none_when_no_search_has_run(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    assert latest_report_path() is None


def test_summarize_mentions_counts_failed_sites_and_saved_path():
    local_listing = make_listing("1", "Analista De Dados", location="São Bernardo do Campo - SP")
    report = run_job_search(
        make_resume(), adapters={"infojobs": FakeAdapter([local_listing]), "gupy": FakeAdapter(fail=True)}
    )

    text = summarize(report, "/tmp/vagas_20260811.md")

    assert "1 vagas presenciais" in text
    assert "gupy" in text
    assert "/tmp/vagas_20260811.md" in text
    assert "Analista De Dados" in text
