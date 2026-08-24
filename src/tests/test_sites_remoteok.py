import json

import pytest

from resume.schema import Resume
from sites.base import SessionStatus, UpdatePlan
from sites.remoteok import RemoteOkAdapter, _card_to_job_listing, _fetch_listings, _slugify_tag


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


LEGAL_BLOB = {"legal": "API Terms of Service: ...", "last_updated": 123}

REAL_SHAPED_CARD = {
    "id": "1130826",
    "position": "Principal Machine Learning Engineer",
    "company": "Attentive",
    "location": "United States",
    "url": "https://remoteOK.com/remote-jobs/remote-principal-machine-learning-engineer-attentive-1130826",
    "description": "<p>We need a <b>Machine Learning</b> engineer with SQL experience.</p>",
    "tags": ["machine learning", "engineer"],
    "salary_min": 150000,
    "salary_max": 200000,
}


def test_slugify_tag_matches_cathos_own_convention():
    assert _slugify_tag("Data Analyst") == "data-analyst"
    assert _slugify_tag("Análise de Dados") == "analise-de-dados"
    assert _slugify_tag("  Python  ") == "python"


def test_card_to_job_listing_converts_a_real_shaped_card():
    listing = _card_to_job_listing(REAL_SHAPED_CARD)

    assert listing.site_name == "remoteok"
    assert listing.external_id == "1130826"
    assert listing.title == "Principal Machine Learning Engineer"
    assert listing.company == "Attentive"
    # Honest, not fabricated -- every RemoteOK listing is remote by
    # definition, and its own location field doesn't reliably say so.
    assert listing.location == "Remote (United States)"
    assert listing.url == REAL_SHAPED_CARD["url"]
    assert "Machine Learning" in listing.snippet
    assert "<b>" not in listing.snippet  # HTML stripped
    assert listing.salary == "US$ 150,000 - US$ 200,000"


def test_card_to_job_listing_location_defaults_to_bare_remote_when_missing():
    card = {**REAL_SHAPED_CARD, "location": ""}

    listing = _card_to_job_listing(card)

    assert listing.location == "Remote"


def test_card_to_job_listing_no_salary_when_either_bound_is_missing():
    card = {**REAL_SHAPED_CARD, "salary_min": 0, "salary_max": 0}

    listing = _card_to_job_listing(card)

    assert listing.salary is None


def test_card_to_job_listing_skips_the_legal_attribution_blob():
    # The real response's first element is never a job -- confirmed live.
    assert _card_to_job_listing(LEGAL_BLOB) is None


def test_card_to_job_listing_none_when_required_fields_missing():
    assert _card_to_job_listing({"id": "1", "position": None, "url": "https://x"}) is None
    assert _card_to_job_listing({"id": "1", "position": "X", "url": None}) is None
    assert _card_to_job_listing({"id": None, "position": "X", "url": "https://x"}) is None


def test_fetch_listings_parses_a_real_shaped_response(monkeypatch):
    import sites.remoteok as remoteok

    monkeypatch.setattr(
        remoteok.urllib.request, "urlopen", _urlopen_returning([LEGAL_BLOB, REAL_SHAPED_CARD])
    )

    cards = _fetch_listings("machine-learning")

    assert cards == [LEGAL_BLOB, REAL_SHAPED_CARD]


def test_fetch_listings_returns_empty_list_on_malformed_json(monkeypatch):
    import sites.remoteok as remoteok

    def _fake(req, timeout=None):
        return FakeResponse(b'{"not": "valid json{{{')

    monkeypatch.setattr(remoteok.urllib.request, "urlopen", _fake)

    assert _fetch_listings("sql") == []


def test_fetch_listings_returns_empty_list_on_network_error(monkeypatch):
    import urllib.error

    import sites.remoteok as remoteok

    def _raise(req, timeout=None):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(remoteok.urllib.request, "urlopen", _raise)

    assert _fetch_listings("sql") == []


def test_fetch_listings_returns_empty_list_when_response_is_not_a_list(monkeypatch):
    import sites.remoteok as remoteok

    monkeypatch.setattr(remoteok.urllib.request, "urlopen", _urlopen_returning({"error": "rate limited"}))

    assert _fetch_listings("sql") == []


def test_search_jobs_converts_valid_cards_and_skips_the_legal_blob(monkeypatch):
    import sites.remoteok as remoteok

    monkeypatch.setattr(
        remoteok.urllib.request, "urlopen", _urlopen_returning([LEGAL_BLOB, REAL_SHAPED_CARD])
    )

    listings = RemoteOkAdapter().search_jobs("Machine Learning")

    assert len(listings) == 1
    assert listings[0].external_id == "1130826"


def test_search_jobs_falls_back_to_the_first_word_when_the_full_slug_has_no_real_jobs(monkeypatch):
    # Real, confirmed-live gap: "data-analyst" (the exact tag this
    # résumé's own target_roles slugify to) returns only the response's
    # always-present legal/attribution entry (no real jobs), while the
    # bare first word "data" alone returns real matches.
    import sites.remoteok as remoteok

    calls = []

    def _fake(req, timeout=None):
        calls.append(req.full_url)
        if "tags=data-analyst" in req.full_url:
            return FakeResponse(json.dumps([LEGAL_BLOB]).encode("utf-8"))
        return FakeResponse(json.dumps([LEGAL_BLOB, REAL_SHAPED_CARD]).encode("utf-8"))

    monkeypatch.setattr(remoteok.urllib.request, "urlopen", _fake)

    listings = RemoteOkAdapter().search_jobs("Data Analyst")

    assert len(listings) == 1
    assert any("tags=data-analyst" in url for url in calls)
    assert any("tags=data" in url and "tags=data-analyst" not in url for url in calls)


def test_search_jobs_does_not_fall_back_for_a_single_word_query(monkeypatch):
    import sites.remoteok as remoteok

    calls = []

    def _fake(req, timeout=None):
        calls.append(req.full_url)
        return FakeResponse(json.dumps([LEGAL_BLOB]).encode("utf-8"))

    monkeypatch.setattr(remoteok.urllib.request, "urlopen", _fake)

    listings = RemoteOkAdapter().search_jobs("Python")

    assert listings == []
    assert len(calls) == 1  # no second, redundant fetch for a query with only one word


def test_search_jobs_respects_max_results(monkeypatch):
    import sites.remoteok as remoteok

    cards = [LEGAL_BLOB] + [
        {**REAL_SHAPED_CARD, "id": str(i), "url": f"https://remoteok.com/remote-jobs/{i}"} for i in range(10)
    ]
    monkeypatch.setattr(remoteok.urllib.request, "urlopen", _urlopen_returning(cards))

    listings = RemoteOkAdapter().search_jobs("Python", max_results=3)

    assert len(listings) == 3


def test_check_session_always_authenticated_no_login_exists():
    assert RemoteOkAdapter().check_session() == SessionStatus.AUTHENTICATED


def test_profile_methods_raise_not_implemented():
    adapter = RemoteOkAdapter()

    with pytest.raises(NotImplementedError):
        adapter.inspect_current_profile()
    with pytest.raises(NotImplementedError):
        adapter.build_update_plan(resume=None, current=None)
    with pytest.raises(NotImplementedError):
        adapter.preview_changes(plan=UpdatePlan(site_name="remoteok"))
    with pytest.raises(NotImplementedError):
        adapter.apply_changes(plan=UpdatePlan(site_name="remoteok"), confirmed=True)
