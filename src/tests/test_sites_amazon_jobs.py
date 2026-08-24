import pytest

from sites import session
from sites.amazon_jobs import AmazonJobsAdapter, _card_to_job_listing, _extract_job_id
from sites.base import SessionStatus


def test_extract_job_id_from_a_real_shaped_url():
    # Real, confirmed live: amazon.jobs job ids sit in the URL's own
    # /jobs/<id>/ path segment.
    url = "https://www.amazon.jobs/en/jobs/3097850/analista-dados-operacoes"

    assert _extract_job_id(url) == "3097850"


def test_extract_job_id_none_for_malformed_or_missing_input():
    assert _extract_job_id("https://www.amazon.jobs/en/search") is None
    assert _extract_job_id(None) is None


def test_card_to_job_listing_converts_a_real_shaped_card():
    card = {
        "title": "Analista Dados, Operações",
        "link": "https://www.amazon.jobs/en/jobs/3097850/analista-dados-operacoes",
        "location": "Cajamar, SP, BRA",
    }

    listing = _card_to_job_listing(card)

    assert listing.site_name == "amazon_jobs"
    assert listing.external_id == "3097850"
    assert listing.company == "Amazon"  # hardcoded -- see module docstring
    assert listing.location == "Cajamar, SP, BRA"
    assert listing.url == card["link"]


def test_card_to_job_listing_none_when_title_or_link_missing():
    assert _card_to_job_listing({"title": None, "link": "https://x", "location": None}) is None
    assert _card_to_job_listing({"title": "X", "link": None, "location": None}) is None


def test_check_session_always_authenticated_no_login_exists():
    # Public search only -- see module docstring.
    assert AmazonJobsAdapter().check_session() == SessionStatus.AUTHENTICATED


def test_inspect_current_profile_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        AmazonJobsAdapter().inspect_current_profile()


class FakeSearchPage:
    def __init__(self, cards):
        # Accepts either a flat list of card dicts (single page) or a
        # list of pages (list of lists) for pagination tests -- same
        # convention as test_sites_catho.py's FakeSearchPage.
        self._pages = [cards] if not cards or isinstance(cards[0], dict) else cards
        self.goto_calls: list[str] = []
        self._evaluate_calls = 0

    def goto(self, url, timeout=None, wait_until=None):
        self.goto_calls.append(url)

    def wait_for_load_state(self, state, timeout=None):
        pass

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        result = self._pages[self._evaluate_calls] if self._evaluate_calls < len(self._pages) else []
        self._evaluate_calls += 1
        return result


class FakeSearchContext:
    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_page(self):
        return self._page

    def close(self):
        self.closed = True


class FakeSearchPlaywright:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_search_jobs_builds_the_real_url_with_query_and_location(monkeypatch):
    cards = [{"title": "Analista Dados, Operações", "link": "https://www.amazon.jobs/en/jobs/1/x", "location": "SP"}]
    page = FakeSearchPage(cards)
    monkeypatch.setattr(
        session, "open_context", lambda site_name, *, headless: (FakeSearchPlaywright(), FakeSearchContext(page))
    )

    listings = AmazonJobsAdapter().search_jobs("analista de dados", location="São Paulo, Brazil")

    assert len(listings) == 1
    assert listings[0].external_id == "1"
    # Page 1 has fewer than max_results, so it pages on to offset=10,
    # which comes back empty (real end of results) and stops there.
    assert page.goto_calls == [
        "https://www.amazon.jobs/en/search?base_query=analista%20de%20dados&loc_query=S%C3%A3o%20Paulo%2C%20Brazil&offset=0",
        "https://www.amazon.jobs/en/search?base_query=analista%20de%20dados&loc_query=S%C3%A3o%20Paulo%2C%20Brazil&offset=10",
    ]


def test_search_jobs_paginates_until_max_results_or_an_empty_page(monkeypatch):
    page_1 = [
        {"title": f"Data Analyst {i}", "link": f"https://www.amazon.jobs/en/jobs/{i}/x", "location": "SP"}
        for i in range(1, 11)
    ]
    page_2 = [
        {"title": f"Data Analyst {i}", "link": f"https://www.amazon.jobs/en/jobs/{i}/x", "location": "SP"}
        for i in range(11, 16)
    ]
    page = FakeSearchPage([page_1, page_2])
    monkeypatch.setattr(
        session, "open_context", lambda site_name, *, headless: (FakeSearchPlaywright(), FakeSearchContext(page))
    )

    listings = AmazonJobsAdapter().search_jobs("data", max_results=15)

    assert len(listings) == 15
    assert page.goto_calls == [
        "https://www.amazon.jobs/en/search?base_query=data&loc_query=S%C3%A3o%20Paulo%2C%20Brazil&offset=0",
        "https://www.amazon.jobs/en/search?base_query=data&loc_query=S%C3%A3o%20Paulo%2C%20Brazil&offset=10",
    ]


def test_search_jobs_stops_on_empty_page_and_closes_context(monkeypatch):
    page = FakeSearchPage([])
    fake_context = FakeSearchContext(page)
    fake_p = FakeSearchPlaywright()
    monkeypatch.setattr(session, "open_context", lambda site_name, *, headless: (fake_p, fake_context))

    listings = AmazonJobsAdapter().search_jobs("data")

    assert listings == []
    assert fake_context.closed is True
    assert fake_p.stopped is True
