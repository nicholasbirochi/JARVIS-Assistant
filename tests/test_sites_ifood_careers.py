import pytest

from jarvis.sites import session
from jarvis.sites.base import SessionStatus
from jarvis.sites.ifood_careers import IFoodCareersAdapter, _card_to_job_listing, _extract_job_id


def test_extract_job_id_from_a_real_shaped_url():
    assert _extract_job_id("https://carreiras.ifood.com.br/job/8687356002/") == "8687356002"


def test_extract_job_id_none_for_malformed_or_missing_input():
    assert _extract_job_id("https://carreiras.ifood.com.br/jobs/") is None
    assert _extract_job_id(None) is None


def test_card_to_job_listing_converts_a_real_shaped_card_with_level():
    card = {
        "title": "Analista BI Pleno",
        "href": "https://carreiras.ifood.com.br/job/8687356002/",
        "level": "Pleno",
        "location": "Brasil",
    }

    listing = _card_to_job_listing(card)

    assert listing.site_name == "ifood_careers"
    assert listing.external_id == "8687356002"
    assert listing.company == "iFood"
    assert listing.title == "Analista BI Pleno (Pleno)"
    assert listing.location == "Brasil"
    assert listing.url == card["href"]


def test_card_to_job_listing_without_level():
    card = {"title": "Analista de Dados", "href": "https://carreiras.ifood.com.br/job/1/", "level": None, "location": "Brasil"}

    listing = _card_to_job_listing(card)

    assert listing.title == "Analista de Dados"


def test_card_to_job_listing_none_when_title_or_href_missing():
    assert _card_to_job_listing({"title": None, "href": "https://x", "level": None, "location": None}) is None
    assert _card_to_job_listing({"title": "X", "href": None, "level": None, "location": None}) is None


def test_check_session_always_authenticated_no_login_exists():
    assert IFoodCareersAdapter().check_session() == SessionStatus.AUTHENTICATED


def test_inspect_current_profile_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        IFoodCareersAdapter().inspect_current_profile()


class FakePage:
    def __init__(self, cards):
        self.cards = cards
        self.goto_calls: list[str] = []

    def goto(self, url, timeout=None, wait_until=None):
        self.goto_calls.append(url)

    def wait_for_load_state(self, state, timeout=None):
        pass

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


def test_search_jobs_fetches_the_full_listing_page_regardless_of_query(monkeypatch):
    cards = [
        {"title": "Analista BI Pleno", "href": "https://carreiras.ifood.com.br/job/1/", "level": "Pleno", "location": "Brasil"},
        {"title": None, "href": None, "level": None, "location": None},
    ]
    page = FakePage(cards)
    monkeypatch.setattr(session, "open_context", lambda site_name, *, headless: (FakePlaywright(), FakeContext(page)))

    listings = IFoodCareersAdapter().search_jobs("qualquer coisa")

    assert len(listings) == 1
    assert listings[0].external_id == "1"
    assert page.goto_calls == ["https://carreiras.ifood.com.br/jobs/"]


def test_search_jobs_respects_max_results(monkeypatch):
    cards = [
        {"title": f"Vaga {i}", "href": f"https://carreiras.ifood.com.br/job/{i}/", "level": None, "location": "Brasil"}
        for i in range(1, 6)
    ]
    page = FakePage(cards)
    monkeypatch.setattr(session, "open_context", lambda site_name, *, headless: (FakePlaywright(), FakeContext(page)))

    listings = IFoodCareersAdapter().search_jobs("x", max_results=3)

    assert len(listings) == 3


def test_search_jobs_closes_context_and_stops_playwright(monkeypatch):
    page = FakePage([])
    fake_context = FakeContext(page)
    fake_p = FakePlaywright()
    monkeypatch.setattr(session, "open_context", lambda site_name, *, headless: (fake_p, fake_context))

    IFoodCareersAdapter().search_jobs("x")

    assert fake_context.closed is True
    assert fake_p.stopped is True
