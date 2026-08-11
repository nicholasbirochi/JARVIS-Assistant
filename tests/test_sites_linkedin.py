import pytest

from jarvis import config
from jarvis.sites.base import SessionStatus
from jarvis.sites.linkedin import LinkedInAdapter, _is_authenticated


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
