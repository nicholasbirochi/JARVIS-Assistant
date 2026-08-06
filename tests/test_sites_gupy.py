import pytest

from jarvis import config
from jarvis.resume.schema import Bilingual, PersonalInfo, Resume
from jarvis.sites.base import SiteProfileSnapshot
from jarvis.sites.gupy import (
    GupyAdapter,
    _is_authenticated,
    _map_resume_to_gupy_fields,
    _strip_country_code,
)


def make_resume(**personal_info_overrides) -> Resume:
    defaults = {
        "full_name": "Nicholas Birochi",
        "phone": "+55 11 90000-0000",
        "email": "nicholas@example.com",
    }
    defaults.update(personal_info_overrides)
    return Resume(
        personal_info=PersonalInfo(**defaults),
        summary=Bilingual(pt="Resumo em português."),
    )


def test_strip_country_code():
    assert _strip_country_code("+55 11 90000-0000") == "11 90000-0000"
    assert _strip_country_code("+5511 90000-0000") == "11 90000-0000"
    assert _strip_country_code(None) is None


def test_map_resume_to_gupy_fields():
    resume = make_resume()

    fields = _map_resume_to_gupy_fields(resume)

    # Gupy stores name/last name separately and no country code on the
    # phone field -- but the mapping still exposes a single "full_name" /
    # already-stripped "phone" for comparison purposes against the scraped
    # snapshot, which normalizes the same way (see _scrape_profile_fields).
    assert fields == {
        "full_name": "Nicholas Birochi",
        "phone": "11 90000-0000",
        "email": "nicholas@example.com",
    }


class FakePage:
    """Stand-in for a Playwright Page -- just enough of input_value() to
    exercise _scrape_profile_fields without a real browser."""

    def __init__(self, values: dict[str, str]):
        self._values = values

    def input_value(self, selector: str) -> str:
        return self._values[selector]


def test_scrape_profile_fields_combines_name_and_last_name():
    page = FakePage(
        {
            "#name": "Nicholas",
            "#lastName": "Birochi",
            "#input-with-button-email-input": "nicholas@example.com",
            "#input-phone-mobileNumber": "(11) 95827-5250",
        }
    )
    adapter = GupyAdapter()

    fields = adapter._scrape_profile_fields(page)

    assert fields == {
        "full_name": "Nicholas Birochi",
        "email": "nicholas@example.com",
        "phone": "(11) 95827-5250",
    }


def test_build_update_plan_only_includes_differing_fields():
    resume = make_resume()
    current = SiteProfileSnapshot(
        site_name="gupy",
        fields={
            "full_name": "Nicholas Birochi",  # same -- no change needed
            "phone": "11 99999-9999",  # different -- change needed
            "email": "nicholas@example.com",  # same
        },
    )
    adapter = GupyAdapter()

    plan = adapter.build_update_plan(resume, current)

    assert plan.site_name == "gupy"
    changed_fields = {c.site_field for c in plan.changes}
    assert changed_fields == {"phone"}


def test_build_update_plan_empty_when_nothing_differs():
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="gupy", fields=_map_resume_to_gupy_fields(resume))
    adapter = GupyAdapter()

    plan = adapter.build_update_plan(resume, current)

    assert plan.changes == []


def test_build_update_plan_skips_fields_missing_locally():
    # phone is None locally -- don't propose overwriting Gupy's value with
    # nothing just because the local résumé hasn't got it filled in.
    resume = make_resume(phone=None)
    current = SiteProfileSnapshot(
        site_name="gupy",
        fields={**_map_resume_to_gupy_fields(resume), "phone": "11 99999-9999"},
    )
    adapter = GupyAdapter()

    plan = adapter.build_update_plan(resume, current)

    assert plan.changes == []


def test_preview_changes_reports_no_changes():
    adapter = GupyAdapter()
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="gupy", fields=_map_resume_to_gupy_fields(resume))
    plan = adapter.build_update_plan(resume, current)

    preview = adapter.preview_changes(plan)

    assert "Nenhuma mudança" in preview.summary_text


def test_preview_changes_lists_each_change():
    adapter = GupyAdapter()
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="gupy", fields={"phone": "11 99999-9999"})
    plan = adapter.build_update_plan(resume, current)

    preview = adapter.preview_changes(plan)

    assert "phone" in preview.summary_text
    assert "11 90000-0000" in preview.summary_text  # the new value, country code stripped
    assert "personal_info.phone" in preview.summary_text  # traceable to the source


def test_apply_changes_refuses_without_confirmation():
    adapter = GupyAdapter()
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="gupy", fields={"phone": "11 99999-9999"})
    plan = adapter.build_update_plan(resume, current)

    result = adapter.apply_changes(plan, confirmed=False)

    assert result.applied is False
    assert "confirmed=True" in result.error


def test_apply_changes_succeeds_trivially_with_no_changes_even_if_confirmed():
    adapter = GupyAdapter()
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="gupy", fields=_map_resume_to_gupy_fields(resume))
    plan = adapter.build_update_plan(resume, current)

    result = adapter.apply_changes(plan, confirmed=True)

    assert result.applied is True
    assert result.changes_applied == []


class FakeAuthPage:
    def __init__(self, final_url: str, has_login_link: bool):
        self.url = final_url
        self._has_login_link = has_login_link
        self.closed = False

    def goto(self, url):
        pass

    def wait_for_load_state(self, state):
        pass

    def query_selector(self, selector):
        return object() if self._has_login_link else None

    def close(self):
        self.closed = True


class FakeAuthContext:
    def __init__(self, page: FakeAuthPage):
        self._page = page

    def new_page(self):
        return self._page


def test_is_authenticated_true_when_no_login_link_and_no_redirect(monkeypatch):
    monkeypatch.setattr(config, "GUPY_PORTAL_URL", "https://portal.gupy.io/")
    monkeypatch.setattr(config, "GUPY_LOGIN_URL", "https://login.gupy.io/candidates/signin")
    page = FakeAuthPage(final_url="https://portal.gupy.io/", has_login_link=False)

    assert _is_authenticated(FakeAuthContext(page)) is True
    assert page.closed is True  # page is cleaned up either way


def test_is_authenticated_false_when_redirected_to_login(monkeypatch):
    monkeypatch.setattr(config, "GUPY_PORTAL_URL", "https://portal.gupy.io/")
    monkeypatch.setattr(config, "GUPY_LOGIN_URL", "https://login.gupy.io/candidates/signin")
    page = FakeAuthPage(final_url="https://login.gupy.io/candidates/signin", has_login_link=False)

    assert _is_authenticated(FakeAuthContext(page)) is False


def test_is_authenticated_false_when_entrar_link_still_present(monkeypatch):
    # The real bug this guards against: portal.gupy.io doesn't redirect an
    # anonymous visitor away, so the URL alone looked "authenticated" even
    # with no real session -- the "Entrar" link is the real tell.
    monkeypatch.setattr(config, "GUPY_PORTAL_URL", "https://portal.gupy.io/")
    monkeypatch.setattr(config, "GUPY_LOGIN_URL", "https://login.gupy.io/candidates/signin")
    page = FakeAuthPage(final_url="https://portal.gupy.io/", has_login_link=True)

    assert _is_authenticated(FakeAuthContext(page)) is False


def test_apply_changes_raises_not_implemented_for_real_submission():
    # Submitting a real change hasn't been tested against the live site yet
    # (see gupy.py's module docstring) -- must fail loudly, not silently
    # pretend to have submitted something.
    adapter = GupyAdapter()
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="gupy", fields={"phone": "11 99999-9999"})
    plan = adapter.build_update_plan(resume, current)

    with pytest.raises(NotImplementedError):
        adapter.apply_changes(plan, confirmed=True)
