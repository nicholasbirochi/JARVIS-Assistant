import pytest

from jarvis import config
from jarvis.sites import session
from jarvis.sites.base import SessionStatus
from jarvis.sites.linkedin import LinkedInAdapter, _card_to_job_listing, _is_authenticated, _parse_card_text


class FakeAuthPage:
    def __init__(self, final_url: str):
        self.url = final_url
        self.closed = False

    def goto(self, url, timeout=None, wait_until=None):
        pass

    def wait_for_timeout(self, ms):
        pass

    def close(self):
        self.closed = True


class FakeAuthContext:
    def __init__(self, page: FakeAuthPage):
        self._page = page

    def new_page(self):
        return self._page


def test_is_authenticated_true_when_not_redirected_to_login(monkeypatch):
    monkeypatch.setattr(config, "LINKEDIN_LOGIN_URL", "https://www.linkedin.com/login")
    page = FakeAuthPage(final_url="https://www.linkedin.com/feed/")

    assert _is_authenticated(FakeAuthContext(page)) is True
    assert page.closed is True


def test_is_authenticated_false_when_still_on_login_page(monkeypatch):
    monkeypatch.setattr(config, "LINKEDIN_LOGIN_URL", "https://www.linkedin.com/login")
    page = FakeAuthPage(final_url="https://www.linkedin.com/login")

    assert _is_authenticated(FakeAuthContext(page)) is False


def test_check_session_not_logged_in_without_a_saved_session(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SITES_STATE_DIR", tmp_path)

    assert LinkedInAdapter().check_session() == SessionStatus.NOT_LOGGED_IN


def test_profile_editing_methods_are_permanently_out_of_scope():
    # Deliberate distinction from every other adapter's early skeleton:
    # this isn't "not implemented yet" -- profile editing on LinkedIn is
    # intentionally excluded, see linkedin.py's module docstring.
    adapter = LinkedInAdapter()

    with pytest.raises(NotImplementedError, match="fora de escopo"):
        adapter.inspect_current_profile()
    with pytest.raises(NotImplementedError, match="fora de escopo"):
        adapter.build_update_plan(resume=None, current=None)
    with pytest.raises(NotImplementedError, match="fora de escopo"):
        adapter.preview_changes(plan=None)
    with pytest.raises(NotImplementedError, match="fora de escopo"):
        adapter.apply_changes(plan=None, confirmed=True)


def test_parse_card_text_with_verified_badge_and_duplicate_title_line():
    # Real, live-confirmed shape: the title appears twice (once inside a
    # visually-hidden accessibility duplicate), and a "(Vaga verificada)"
    # badge is appended only to the first occurrence.
    text = (
        "DATA ANALYST I (Vaga verificada)\nDATA ANALYST I \n\nInter\n\n"
        "Belo Horizonte, MG (Presencial)\n\nAvaliando candidaturas\n\nVisto"
    )

    fields = _parse_card_text(text)

    assert fields == {"title": "DATA ANALYST I", "company": "Inter", "location": "Belo Horizonte, MG (Presencial)"}


def test_parse_card_text_without_badge_or_duplicate_line():
    text = "ANALISTA DADOS JR\n\nGrupo Ri Happy\n\nSão Paulo, SP (Híbrido)\n\n1 ex-aluno da instituição trabalha aqui"

    fields = _parse_card_text(text)

    assert fields == {"title": "ANALISTA DADOS JR", "company": "Grupo Ri Happy", "location": "São Paulo, SP (Híbrido)"}


def test_parse_card_text_missing_fields_default_to_none():
    assert _parse_card_text("Só Um Título") == {"title": "Só Um Título", "company": None, "location": None}
    assert _parse_card_text("") == {"title": None, "company": None, "location": None}


def test_card_to_job_listing_converts_a_real_shaped_card():
    card = {
        "jobId": "4441485838",
        "text": "DATA ANALYST I (Vaga verificada)\nDATA ANALYST I \n\nInter\n\nBelo Horizonte, MG (Presencial)",
    }

    listing = _card_to_job_listing(card)

    assert listing.site_name == "linkedin"
    assert listing.external_id == "4441485838"
    assert listing.title == "DATA ANALYST I"
    assert listing.company == "Inter"
    assert listing.url == "https://www.linkedin.com/jobs/view/4441485838/"


def test_card_to_job_listing_none_for_malformed_or_titleless_cards():
    assert _card_to_job_listing({"jobId": "not-a-number", "text": "Título\n\nEmpresa"}) is None
    assert _card_to_job_listing({"jobId": "123456", "text": ""}) is None
    assert _card_to_job_listing({"jobId": None, "text": "Título\n\nEmpresa"}) is None


class FakeSearchPage:
    def __init__(self, cards: list[dict]):
        self._cards = cards
        self.goto_calls = []

    def goto(self, url, timeout=None, wait_until=None):
        self.goto_calls.append(url)

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        return self._cards


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


def test_search_jobs_builds_the_real_query_url_and_converts_valid_cards(monkeypatch):
    cards = [
        {"jobId": "4441485838", "text": "Analista De Dados\n\nEmpresa X\n\nSão Paulo, SP"},
        {"jobId": "not-a-number", "text": "Lixo\n\nEmpresa"},
    ]
    page = FakeSearchPage(cards)
    seen_kwargs = {}

    def fake_open_context(site_name, *, headless, off_screen=False):
        seen_kwargs["headless"] = headless
        seen_kwargs["off_screen"] = off_screen
        return FakeSearchPlaywright(), FakeSearchContext(page)

    monkeypatch.setattr(session, "open_context", fake_open_context)

    listings = LinkedInAdapter().search_jobs("Analista de Dados")

    assert len(listings) == 1
    assert listings[0].external_id == "4441485838"
    assert page.goto_calls == ["https://www.linkedin.com/jobs/search-results/?keywords=Analista+de+Dados"]
    # 2026-08-19: off_screen=True so this required headed window doesn't
    # pop up visibly (see session.py's open_context docstring).
    assert seen_kwargs == {"headless": False, "off_screen": True}


def test_search_jobs_accepts_max_results_for_run_job_search_compatibility(monkeypatch):
    # jarvis.job_search.run_job_search() always calls
    # adapter.search_jobs(term, max_results=...) -- this adapter has no
    # real pagination, but must at least accept and honor the cap rather
    # than raising a TypeError when wired into that call convention
    # (2026-08-19, wired into jarvis.job_portal.server._portal_adapters()).
    cards = [
        {"jobId": str(1000000000 + i), "text": f"Vaga {i}\n\nEmpresa\n\nSão Paulo, SP"} for i in range(5)
    ]
    page = FakeSearchPage(cards)
    monkeypatch.setattr(
        session,
        "open_context",
        lambda site_name, *, headless, off_screen=False: (FakeSearchPlaywright(), FakeSearchContext(page)),
    )

    listings = LinkedInAdapter().search_jobs("Analista de Dados", max_results=2)

    assert len(listings) == 2
