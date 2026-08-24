import pytest

import config
from sites import session
from sites.base import SessionStatus
from sites.catho import CathoAdapter, _card_to_job_listing, _is_authenticated, _slugify


class FakeAuthPage:
    def __init__(self, final_url: str):
        self.url = final_url
        self.closed = False

    def goto(self, url):
        pass

    def wait_for_load_state(self, state):
        pass

    def close(self):
        self.closed = True


class FakeAuthContext:
    def __init__(self, page: FakeAuthPage):
        self._page = page

    def new_page(self):
        return self._page


def test_is_authenticated_true_when_not_redirected_to_signin(monkeypatch):
    monkeypatch.setattr(config, "CATHO_LOGIN_URL", "https://www.catho.com.br/signin/")
    page = FakeAuthPage(final_url="https://www.catho.com.br/candidato/perfil/")

    assert _is_authenticated(FakeAuthContext(page)) is True
    assert page.closed is True  # page is cleaned up either way


def test_is_authenticated_false_when_still_on_signin_page(monkeypatch):
    monkeypatch.setattr(config, "CATHO_LOGIN_URL", "https://www.catho.com.br/signin/")
    page = FakeAuthPage(final_url="https://www.catho.com.br/signin/")

    assert _is_authenticated(FakeAuthContext(page)) is False


def test_check_session_not_logged_in_without_a_saved_session(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SITES_STATE_DIR", tmp_path)

    assert CathoAdapter().check_session() == SessionStatus.NOT_LOGGED_IN


def test_check_session_always_opens_headed_regardless_of_sites_headless_config(monkeypatch, tmp_path):
    # Real, confirmed constraint (see catho.py's module docstring):
    # headless=True gets served a 403 page by this site specifically.
    from sites import session

    monkeypatch.setattr(config, "SITES_STATE_DIR", tmp_path)
    (tmp_path / "catho_state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "SITES_HEADLESS", True)  # the global default -- must be ignored here

    seen_headless = []

    class DummyPlaywright:
        def stop(self):
            pass

    class DummyContext:
        def new_page(self):
            raise RuntimeError("stop here -- only checking how open_context was called")

        def close(self):
            pass

    def fake_open_context(site_name, *, headless):
        seen_headless.append(headless)
        return DummyPlaywright(), DummyContext()

    monkeypatch.setattr(session, "open_context", fake_open_context)

    status = CathoAdapter().check_session()

    assert seen_headless == [False]
    assert status == SessionStatus.UNKNOWN_ERROR  # DummyContext.new_page() raising is expected here


def test_profile_methods_raise_not_implemented_until_the_real_site_is_inspected():
    # Deliberate: the profile edit page is only reachable authenticated,
    # so its real URL/selectors can't be found without a live, logged-in
    # session -- see catho.py's module docstring. Each of these must say
    # so clearly, not guess.
    adapter = CathoAdapter()

    with pytest.raises(NotImplementedError):
        adapter.inspect_current_profile()
    with pytest.raises(NotImplementedError):
        adapter.build_update_plan(resume=None, current=None)
    with pytest.raises(NotImplementedError):
        adapter.preview_changes(plan=None)
    with pytest.raises(NotImplementedError):
        adapter.apply_changes(plan=None, confirmed=True)


def test_slugify():
    # Verified live: these exact slugs return real, correctly-titled Catho
    # search-results pages.
    assert _slugify("Analista de Dados") == "analista-de-dados"
    assert _slugify("Business Intelligence") == "business-intelligence"
    assert _slugify("Power BI") == "power-bi"
    assert _slugify("Análise de Dados Júnior") == "analise-de-dados-junior"


def test_card_to_job_listing_converts_a_real_shaped_card():
    card = {
        "external_id": "37907324",
        "title": "Analista de Banco de Dados",
        "href": "/vagas/analista-de-banco-de-dados/37907324",
        "company": "LUANDRE SERVICOS TEMPORARIOS LTDA. (C-I)",
        "location": "4 vagas - Piracicaba",
    }

    listing = _card_to_job_listing(card)

    assert listing.site_name == "catho"
    assert listing.external_id == "37907324"
    assert listing.url == "https://www.catho.com.br/vagas/analista-de-banco-de-dados/37907324"
    assert listing.company == "LUANDRE SERVICOS TEMPORARIOS LTDA. (C-I)"


def test_card_to_job_listing_none_for_a_card_missing_title_or_href():
    assert _card_to_job_listing({"external_id": "1", "title": None, "href": "/x"}) is None
    assert _card_to_job_listing({"external_id": "1", "title": "X", "href": None}) is None
    assert _card_to_job_listing({"external_id": None, "title": "X", "href": "/x"}) is None


class FakeConsentButton:
    def __init__(self, visible: bool):
        self._visible = visible
        self.clicked = False

    def is_visible(self):
        return self._visible

    def click(self):
        self.clicked = True


class FakeSearchPage:
    def __init__(self, cards: list[dict], *, consent_button: FakeConsentButton | None = None):
        # Accepts either a flat list of card dicts (single page, wrapped
        # here) or a list of pages (list of lists) for pagination tests.
        self._pages = [cards] if not cards or isinstance(cards[0], dict) else cards
        self.consent_button = consent_button
        self.goto_calls = []
        self._evaluate_calls = 0

    def goto(self, url, timeout=None, wait_until=None):
        self.goto_calls.append(url)

    def wait_for_timeout(self, ms):
        pass

    def query_selector(self, selector):
        if selector == "button.acceptAll":
            return self.consent_button
        return None

    def evaluate(self, script):
        # Each goto() call is followed by exactly one evaluate() call in
        # search_jobs() -- use that 1:1 pairing to hand back one "page" of
        # cards per call, then an empty list once pages run out (real end
        # of results).
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
    def stop(self):
        pass


def test_search_jobs_builds_the_real_slug_url_and_converts_valid_cards(monkeypatch):
    cards = [
        {
            "external_id": "1",
            "title": "Analista de Dados",
            "href": "/vagas/analista-de-dados/1",
            "company": "Empresa",
            "location": "São Paulo",
        },
        {"external_id": None, "title": None, "href": None, "company": None, "location": None},
    ]
    page = FakeSearchPage(cards, consent_button=FakeConsentButton(visible=True))
    monkeypatch.setattr(
        session, "open_context", lambda site_name, *, headless, off_screen=False: (FakeSearchPlaywright(), FakeSearchContext(page))
    )

    listings = CathoAdapter().search_jobs("Analista de Dados")

    assert len(listings) == 1
    assert listings[0].external_id == "1"
    # Page 1 has cards (fewer than max_results), so it pages on to 2 --
    # which comes back empty (real end of results) and stops there.
    assert page.goto_calls == [
        "https://www.catho.com.br/vagas/analista-de-dados/",
        "https://www.catho.com.br/vagas/analista-de-dados/?page=2",
    ]
    assert page.consent_button.clicked is True


def test_search_jobs_paginates_until_max_results_or_an_empty_page(monkeypatch):
    page_1 = [
        {
            "external_id": str(i),
            "title": f"Analista de Dados {i}",
            "href": f"/vagas/analista-de-dados/{i}",
            "company": "Empresa",
            "location": "São Paulo",
        }
        for i in range(1, 21)
    ]
    page_2 = [
        {
            "external_id": str(i),
            "title": f"Analista de Dados {i}",
            "href": f"/vagas/analista-de-dados/{i}",
            "company": "Empresa",
            "location": "São Paulo",
        }
        for i in range(21, 26)
    ]
    page = FakeSearchPage([page_1, page_2], consent_button=None)
    monkeypatch.setattr(
        session, "open_context", lambda site_name, *, headless, off_screen=False: (FakeSearchPlaywright(), FakeSearchContext(page))
    )

    listings = CathoAdapter().search_jobs("Analista de Dados", max_results=25)

    assert len(listings) == 25
    # Stopped after page 2 satisfied max_results -- never requested page 3.
    assert page.goto_calls == [
        "https://www.catho.com.br/vagas/analista-de-dados/",
        "https://www.catho.com.br/vagas/analista-de-dados/?page=2",
    ]


def test_search_jobs_skips_consent_click_when_banner_not_present(monkeypatch):
    page = FakeSearchPage([], consent_button=None)
    monkeypatch.setattr(
        session, "open_context", lambda site_name, *, headless, off_screen=False: (FakeSearchPlaywright(), FakeSearchContext(page))
    )

    listings = CathoAdapter().search_jobs("Analista de Dados")

    assert listings == []
