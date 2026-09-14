import json
import urllib.error

import pytest

from sites.base import SessionStatus, UpdatePlan
from sites.remote_company_boards import (
    RemoteCompanyBoardsAdapter,
    _fetch_ashby_jobs,
    _fetch_greenhouse_jobs,
    fetch_all_companies,
)


class FakeResponse:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _urlopen_returning(payload) -> callable:
    body = json.dumps(payload).encode("utf-8")

    def _fake(req, timeout=None):
        return FakeResponse(body)

    return _fake


# Real-shaped payloads -- fields confirmed live 2026-09-14 via a direct
# curl of each real API (not just a paraphrased fetch), see module
# docstring.
REAL_ASHBY_JOB = {
    "id": "533f2314-39b0-48c6-a6c2-226242a7d608",
    "title": "Senior Data Scientist",
    "location": "Canada",
    "isRemote": True,
    "jobUrl": "https://jobs.ashbyhq.com/super.com/533f2314-39b0-48c6-a6c2-226242a7d608",
    "descriptionPlain": "Candidates can be based anywhere in Canada, provided they maintain overlap.",
}

REAL_GREENHOUSE_JOB = {
    "id": 8556658002,
    "title": "Engineering Manager - Data Platform",
    "location": {"name": "Home based - Worldwide"},
    "absolute_url": "https://job-boards.greenhouse.io/canonical/jobs/8556658002",
    "content": "&lt;div&gt;&lt;p&gt;Canonical is a &lt;b&gt;remote-first&lt;/b&gt; company.&lt;/p&gt;&lt;/div&gt;",
}


def test_fetch_ashby_jobs_converts_a_real_shaped_job(monkeypatch):
    import sites.remote_company_boards as mod

    monkeypatch.setattr(mod.urllib.request, "urlopen", _urlopen_returning({"jobs": [REAL_ASHBY_JOB]}))

    listings = _fetch_ashby_jobs("Super.com", "super.com")

    assert len(listings) == 1
    listing = listings[0]
    assert listing.site_name == "remote_company_boards"
    # Prefixed with the board token -- ids are only unique WITHIN one
    # company's board, not across the several this module combines.
    assert listing.external_id == "super.com:533f2314-39b0-48c6-a6c2-226242a7d608"
    assert listing.title == "Senior Data Scientist"
    assert listing.company == "Super.com"
    assert listing.location == "Canada"
    assert listing.url == REAL_ASHBY_JOB["jobUrl"]
    assert "based anywhere in Canada" in listing.snippet


def test_fetch_greenhouse_jobs_converts_a_real_shaped_job_and_strips_html(monkeypatch):
    import sites.remote_company_boards as mod

    monkeypatch.setattr(mod.urllib.request, "urlopen", _urlopen_returning({"jobs": [REAL_GREENHOUSE_JOB]}))

    listings = _fetch_greenhouse_jobs("Canonical", "canonical")

    assert len(listings) == 1
    listing = listings[0]
    assert listing.external_id == "canonical:8556658002"
    assert listing.title == "Engineering Manager - Data Platform"
    assert listing.company == "Canonical"
    # location.name, not the whole location object.
    assert listing.location == "Home based - Worldwide"
    assert listing.url == REAL_GREENHOUSE_JOB["absolute_url"]
    # Real, confirmed-live gap: Greenhouse's content is HTML-entity-
    # escaped ON TOP of being HTML ("&lt;div&gt;" etc.) -- both the
    # escaping and the tags themselves must be gone from the snippet.
    assert "<" not in listing.snippet
    assert "&lt;" not in listing.snippet
    assert "remote-first" in listing.snippet


def test_fetch_ashby_jobs_skips_entries_missing_required_fields(monkeypatch):
    import sites.remote_company_boards as mod

    monkeypatch.setattr(
        mod.urllib.request,
        "urlopen",
        _urlopen_returning({"jobs": [{"id": "1", "title": None, "jobUrl": "https://x"}]}),
    )

    assert _fetch_ashby_jobs("Super.com", "super.com") == []


def test_fetch_greenhouse_jobs_skips_entries_missing_required_fields(monkeypatch):
    import sites.remote_company_boards as mod

    monkeypatch.setattr(
        mod.urllib.request,
        "urlopen",
        _urlopen_returning({"jobs": [{"id": None, "title": "X", "absolute_url": "https://x"}]}),
    )

    assert _fetch_greenhouse_jobs("Canonical", "canonical") == []


def test_fetch_json_returns_none_on_network_error(monkeypatch):
    import urllib.error

    import sites.remote_company_boards as mod

    def _raise(req, timeout=None):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(mod.urllib.request, "urlopen", _raise)

    # One company's board being down must not raise -- fails soft to [].
    assert _fetch_ashby_jobs("Super.com", "super.com") == []
    assert _fetch_greenhouse_jobs("Canonical", "canonical") == []


def test_fetch_json_returns_none_on_malformed_json(monkeypatch):
    import sites.remote_company_boards as mod

    def _fake(req, timeout=None):
        return FakeResponse(b'{"not": "valid json{{{')

    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake)

    assert _fetch_ashby_jobs("Super.com", "super.com") == []


def test_fetch_all_companies_combines_every_registered_company(monkeypatch):
    import sites.remote_company_boards as mod

    def _fake(req, timeout=None):
        if "ashbyhq" in req.full_url:
            return FakeResponse(json.dumps({"jobs": [REAL_ASHBY_JOB]}).encode("utf-8"))
        return FakeResponse(json.dumps({"jobs": [REAL_GREENHOUSE_JOB]}).encode("utf-8"))

    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake)

    listings = fetch_all_companies()

    # One listing per registered company (2 Ashby + 2 Greenhouse
    # companies in _COMPANIES, each fake response returning one job).
    assert len(listings) == len(mod._COMPANIES)
    companies_seen = {listing.company for listing in listings}
    assert companies_seen == {c["name"] for c in mod._COMPANIES}


def test_fetch_all_companies_one_companys_failure_does_not_sink_the_others(monkeypatch):
    import sites.remote_company_boards as mod

    def _fake(req, timeout=None):
        if "super.com" in req.full_url:
            raise urllib.error.URLError("boom")
        if "ashbyhq" in req.full_url:
            return FakeResponse(json.dumps({"jobs": [REAL_ASHBY_JOB]}).encode("utf-8"))
        return FakeResponse(json.dumps({"jobs": [REAL_GREENHOUSE_JOB]}).encode("utf-8"))

    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake)

    listings = fetch_all_companies()

    # Zapier (also Ashby) + the 2 Greenhouse companies still come back,
    # only Super.com's own board is missing.
    assert len(listings) == len(mod._COMPANIES) - 1
    assert "Super.com" not in {listing.company for listing in listings}


def test_search_jobs_respects_max_results(monkeypatch):
    import sites.remote_company_boards as mod

    def _fake(req, timeout=None):
        if "ashbyhq" in req.full_url:
            return FakeResponse(json.dumps({"jobs": [REAL_ASHBY_JOB]}).encode("utf-8"))
        return FakeResponse(json.dumps({"jobs": [REAL_GREENHOUSE_JOB]}).encode("utf-8"))

    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake)

    # 4 registered companies, 1 real listing each -- fetch_all_companies()
    # alone would return 4; max_results must actually truncate that.
    listings = RemoteCompanyBoardsAdapter().search_jobs("Data", max_results=2)

    assert len(listings) == 2


def test_check_session_always_authenticated_no_login_exists():
    assert RemoteCompanyBoardsAdapter().check_session() == SessionStatus.AUTHENTICATED


def test_profile_methods_raise_not_implemented():
    adapter = RemoteCompanyBoardsAdapter()

    with pytest.raises(NotImplementedError):
        adapter.inspect_current_profile()
    with pytest.raises(NotImplementedError):
        adapter.build_update_plan(resume=None, current=None)
    with pytest.raises(NotImplementedError):
        adapter.preview_changes(plan=UpdatePlan(site_name="remote_company_boards"))
    with pytest.raises(NotImplementedError):
        adapter.apply_changes(plan=UpdatePlan(site_name="remote_company_boards"), confirmed=True)
