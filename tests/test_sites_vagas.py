import pytest

from jarvis import config
from jarvis.sites.base import SessionStatus
from jarvis.sites.vagas import VagasAdapter, _is_authenticated


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


def test_is_authenticated_true_when_not_redirected_to_login(monkeypatch):
    monkeypatch.setattr(config, "VAGAS_LOGIN_URL", "https://www.vagas.com.br/login-candidatos")
    page = FakeAuthPage(final_url="https://www.vagas.com.br/candidatos/perfil")

    assert _is_authenticated(FakeAuthContext(page)) is True
    assert page.closed is True  # page is cleaned up either way


def test_is_authenticated_false_when_still_on_login_page(monkeypatch):
    monkeypatch.setattr(config, "VAGAS_LOGIN_URL", "https://www.vagas.com.br/login-candidatos")
    page = FakeAuthPage(final_url="https://www.vagas.com.br/login-candidatos")

    assert _is_authenticated(FakeAuthContext(page)) is False


def test_check_session_not_logged_in_without_a_saved_session(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SITES_STATE_DIR", tmp_path)

    assert VagasAdapter().check_session() == SessionStatus.NOT_LOGGED_IN


def test_profile_methods_raise_not_implemented_until_the_real_site_is_inspected():
    # Deliberate: unlike Gupy's public pages, Vagas.com's profile edit page
    # is only reachable authenticated, so its real URL/selectors can't be
    # found without a live, logged-in session -- see vagas.py's module
    # docstring. Each of these must say so clearly, not guess.
    adapter = VagasAdapter()

    with pytest.raises(NotImplementedError):
        adapter.inspect_current_profile()
    with pytest.raises(NotImplementedError):
        adapter.build_update_plan(resume=None, current=None)
    with pytest.raises(NotImplementedError):
        adapter.preview_changes(plan=None)
    with pytest.raises(NotImplementedError):
        adapter.apply_changes(plan=None, confirmed=True)
