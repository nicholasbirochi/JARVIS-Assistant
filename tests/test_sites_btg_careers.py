import pytest

from jarvis.sites import session
from jarvis.sites.base import SessionStatus
from jarvis.sites.btg_careers import BTGCareersAdapter, _card_to_job_listing, _extract_job_id


def test_extract_job_id_from_a_real_shaped_url():
    url = "https://carreiras.btgpactual.com/vagas/asset-management/analista-asset-servicing-real-estate-finance/6145712004"

    assert _extract_job_id(url) == "6145712004"


def test_extract_job_id_none_for_malformed_or_missing_input():
    assert _extract_job_id("https://carreiras.btgpactual.com/vagas") is None
    assert _extract_job_id(None) is None


def test_card_to_job_listing_converts_a_real_shaped_card():
    card = {
        "title": "Analista Asset Servicing | Real Estate Finance",
        "href": "https://carreiras.btgpactual.com/vagas/asset-management/analista-asset-servicing-real-estate-finance/6145712004",
        "location": "São Paulo",
    }

    listing = _card_to_job_listing(card)

    assert listing.site_name == "btg_careers"
    assert listing.external_id == "6145712004"
    assert listing.company == "BTG Pactual"
    assert listing.title == "Analista Asset Servicing | Real Estate Finance"
    assert listing.location == "São Paulo"
    assert listing.url == card["href"]


def test_card_to_job_listing_none_when_title_or_href_missing():
    assert _card_to_job_listing({"title": None, "href": "https://x", "location": None}) is None
    assert _card_to_job_listing({"title": "X", "href": None, "location": None}) is None


def test_check_session_always_authenticated_no_login_exists():
    assert BTGCareersAdapter().check_session() == SessionStatus.AUTHENTICATED


def test_inspect_current_profile_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        BTGCareersAdapter().inspect_current_profile()


class FakePage:
    def __init__(self, cards):
        self.cards = cards
        self.goto_calls: list[str] = []

    def goto(self, url, timeout=None, wait_until=None):
        self.goto_calls.append(url)

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        return self.cards


class FakeContext:
    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_page(self):
        return self._page

    def close(self):
        self.closed = True


class FakePlaywright:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_search_jobs_fetches_the_listing_page_regardless_of_query(monkeypatch):
    cards = [
        {
            "title": "Analista Asset Servicing",
            "href": "https://carreiras.btgpactual.com/vagas/asset-management/x/1",
            "location": "São Paulo",
        },
        {"title": None, "href": None, "location": None},
    ]
    page = FakePage(cards)
    monkeypatch.setattr(session, "open_context", lambda site_name, *, headless: (FakePlaywright(), FakeContext(page)))

    listings = BTGCareersAdapter().search_jobs("qualquer coisa")

    assert len(listings) == 1
    assert listings[0].external_id == "1"
    assert page.goto_calls == ["https://carreiras.btgpactual.com/vagas"]


def test_search_jobs_dedupes_the_same_job_appearing_twice(monkeypatch):
    # Real shape confirmed live: each job's link appears twice (title
    # link + a separate "Ver vaga" link to the same href).
    href = "https://carreiras.btgpactual.com/vagas/asset-management/x/1"
    cards = [
        {"title": "Analista Asset Servicing", "href": href, "location": "São Paulo"},
        {"title": "Analista Asset Servicing", "href": href, "location": "São Paulo"},
    ]
    page = FakePage(cards)
    monkeypatch.setattr(session, "open_context", lambda site_name, *, headless: (FakePlaywright(), FakeContext(page)))

    listings = BTGCareersAdapter().search_jobs("x")

    assert len(listings) == 1


def test_search_jobs_respects_max_results(monkeypatch):
    cards = [
        {
            "title": f"Vaga {i}",
            "href": f"https://carreiras.btgpactual.com/vagas/area/x/{i}",
            "location": "São Paulo",
        }
        for i in range(1, 6)
    ]
    page = FakePage(cards)
    monkeypatch.setattr(session, "open_context", lambda site_name, *, headless: (FakePlaywright(), FakeContext(page)))

    listings = BTGCareersAdapter().search_jobs("x", max_results=3)

    assert len(listings) == 3


def test_search_jobs_closes_context_and_stops_playwright(monkeypatch):
    page = FakePage([])
    fake_context = FakeContext(page)
    fake_p = FakePlaywright()
    monkeypatch.setattr(session, "open_context", lambda site_name, *, headless: (fake_p, fake_context))

    BTGCareersAdapter().search_jobs("x")

    assert fake_context.closed is True
    assert fake_p.stopped is True
