import pytest

from jarvis import config
from jarvis.sites.base import SessionStatus
from jarvis.sites.catho import CathoAdapter, _is_authenticated


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
    from jarvis.sites import session

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
