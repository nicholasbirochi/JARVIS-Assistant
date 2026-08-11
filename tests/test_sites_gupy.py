import json
from pathlib import Path

import pytest

from jarvis import config
from jarvis.resume.schema import Bilingual, PersonalInfo, Resume
from jarvis.sites import session
from jarvis.sites.base import PlannedFieldChange, SiteProfileSnapshot, UpdatePlan
from jarvis.sites.gupy import (
    GupyAdapter,
    _card_to_job_listing,
    _decode_job_id,
    _is_authenticated,
    _map_resume_to_gupy_fields,
    _split_full_name,
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


def test_split_full_name():
    # Verified live against the real account: "Nicholas Birochi" ->
    # #name="Nicholas", #lastName="Birochi".
    assert _split_full_name("Nicholas Birochi") == ("Nicholas", "Birochi")
    assert _split_full_name("Nicholas Silva Birochi") == ("Nicholas", "Silva Birochi")
    assert _split_full_name("Cher") == ("Cher", "")


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


def test_apply_changes_raises_not_implemented_for_email_change(monkeypatch):
    # Email is deliberately excluded from real writes (it's also the login
    # identifier -- see gupy.py's module docstring) -- and the check must
    # happen BEFORE any browser session is opened, not after a failed write.
    def _fail_open_context(site_name, *, headless):
        raise AssertionError("should not open a browser session for an unsupported field")

    monkeypatch.setattr(session, "open_context", _fail_open_context)

    adapter = GupyAdapter()
    resume = make_resume()
    current = SiteProfileSnapshot(
        site_name="gupy", fields={**_map_resume_to_gupy_fields(resume), "email": "old@example.com"}
    )
    plan = adapter.build_update_plan(resume, current)
    assert {c.site_field for c in plan.changes} == {"email"}

    with pytest.raises(NotImplementedError):
        adapter.apply_changes(plan, confirmed=True)


def test_apply_changes_refuses_entire_plan_if_any_field_unsupported(monkeypatch):
    # A plan mixing a supported field (phone) with an unsupported one
    # (email) must refuse the whole thing, not silently write the phone and
    # skip the email.
    def _fail_open_context(site_name, *, headless):
        raise AssertionError("should not open a browser session when any field is unsupported")

    monkeypatch.setattr(session, "open_context", _fail_open_context)

    adapter = GupyAdapter()
    plan = UpdatePlan(
        site_name="gupy",
        changes=[
            PlannedFieldChange(
                site_field="phone",
                current_value="11 90000-0000",
                new_value="11 98888-8888",
                resume_field_path="personal_info.phone",
            ),
            PlannedFieldChange(
                site_field="email",
                current_value="old@example.com",
                new_value="new@example.com",
                resume_field_path="personal_info.email",
            ),
        ],
    )

    with pytest.raises(NotImplementedError):
        adapter.apply_changes(plan, confirmed=True)


class FakeSaveButton:
    def __init__(self):
        self.clicked = False

    def click(self):
        self.clicked = True


class FakeLocator:
    def __init__(self):
        self.blurred = False

    def blur(self):
        self.blurred = True


class FakeApplyPage:
    """Stand-in for a Playwright Page during apply_changes(). `fill()`
    writes straight into the same `values` dict `input_value()`/scraping
    reads from, so a successful fill+save round-trips exactly like the real
    site does -- unless `apply_fills=False`, which simulates a site that
    silently didn't persist the change (the failure case we must detect)."""

    def __init__(self, values: dict[str, str], *, has_save_button: bool = True, apply_fills: bool = True):
        self.values = dict(values)
        self.has_save_button = has_save_button
        self.apply_fills = apply_fills
        self.save_button = FakeSaveButton()

    def goto(self, url, wait_until=None, timeout=None):
        pass

    def wait_for_load_state(self, state, timeout=None):
        pass

    def fill(self, selector, value):
        if self.apply_fills:
            self.values[selector] = value

    def input_value(self, selector):
        return self.values[selector]

    def locator(self, selector):
        return FakeLocator()

    def query_selector(self, selector):
        if selector == '[data-testid="button-save"]':
            return self.save_button if self.has_save_button else None
        return None


class FakeApplyContext:
    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_page(self):
        return self._page

    def close(self):
        self.closed = True


class FakeApplyPlaywright:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def _base_profile_values(**overrides) -> dict[str, str]:
    values = {
        "#name": "Nicholas",
        "#lastName": "Birochi",
        "#input-with-button-email-input": "nicholas@example.com",
        "#input-phone-mobileNumber": "11 90000-0000",
    }
    values.update(overrides)
    return values


def test_apply_changes_writes_phone_and_full_name_when_supported(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SITES_EVIDENCE_DIR", tmp_path / "evidence")
    resume = make_resume(full_name="Nicholas Silva", phone="+55 11 98888-8888")
    current = SiteProfileSnapshot(
        site_name="gupy",
        fields={"full_name": "Nicholas Birochi", "phone": "11 90000-0000", "email": "nicholas@example.com"},
    )
    adapter = GupyAdapter()
    plan = adapter.build_update_plan(resume, current)
    assert {c.site_field for c in plan.changes} == {"full_name", "phone"}

    page = FakeApplyPage(_base_profile_values())
    monkeypatch.setattr(
        session, "open_context", lambda site_name, *, headless: (FakeApplyPlaywright(), FakeApplyContext(page))
    )

    result = adapter.apply_changes(plan, confirmed=True)

    assert result.applied is True
    assert {c.site_field for c in result.changes_applied} == {"full_name", "phone"}
    assert page.save_button.clicked is True
    assert page.values["#name"] == "Nicholas"
    assert page.values["#lastName"] == "Silva"
    assert page.values["#input-phone-mobileNumber"] == "11 98888-8888"
    assert result.evidence_path is not None

    # Evidence is a small JSON audit record, deliberately NOT a screenshot --
    # the profile page also shows CPF/birth date, which a screenshot would
    # capture incidentally even though the write itself never touches them.
    evidence = json.loads(Path(result.evidence_path).read_text(encoding="utf-8"))
    assert evidence["site_name"] == "gupy"
    assert {c["field"] for c in evidence["changes"]} == {"full_name", "phone"}


def test_apply_changes_reports_failure_if_site_does_not_reflect_change(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SITES_EVIDENCE_DIR", tmp_path / "evidence")
    resume = make_resume(phone="+55 11 98888-8888")
    current = SiteProfileSnapshot(site_name="gupy", fields={**_map_resume_to_gupy_fields(resume), "phone": "11 90000-0000"})
    adapter = GupyAdapter()
    plan = adapter.build_update_plan(resume, current)

    page = FakeApplyPage(_base_profile_values(), apply_fills=False)
    monkeypatch.setattr(
        session, "open_context", lambda site_name, *, headless: (FakeApplyPlaywright(), FakeApplyContext(page))
    )

    result = adapter.apply_changes(plan, confirmed=True)

    assert result.applied is False
    assert "phone" in result.error
    assert page.save_button.clicked is True  # it did try to save


def test_apply_changes_reports_missing_save_button(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SITES_EVIDENCE_DIR", tmp_path / "evidence")
    resume = make_resume(phone="+55 11 98888-8888")
    current = SiteProfileSnapshot(site_name="gupy", fields={**_map_resume_to_gupy_fields(resume), "phone": "11 90000-0000"})
    adapter = GupyAdapter()
    plan = adapter.build_update_plan(resume, current)

    page = FakeApplyPage(_base_profile_values(), has_save_button=False)
    monkeypatch.setattr(
        session, "open_context", lambda site_name, *, headless: (FakeApplyPlaywright(), FakeApplyContext(page))
    )

    result = adapter.apply_changes(plan, confirmed=True)

    assert result.applied is False
    assert "Salvar" in result.error


def test_apply_changes_closes_context_and_stops_playwright_even_on_success(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SITES_EVIDENCE_DIR", tmp_path / "evidence")
    resume = make_resume(phone="+55 11 98888-8888")
    current = SiteProfileSnapshot(site_name="gupy", fields={**_map_resume_to_gupy_fields(resume), "phone": "11 90000-0000"})
    adapter = GupyAdapter()
    plan = adapter.build_update_plan(resume, current)

    page = FakeApplyPage(_base_profile_values())
    fake_context = FakeApplyContext(page)
    fake_p = FakeApplyPlaywright()
    monkeypatch.setattr(session, "open_context", lambda site_name, *, headless: (fake_p, fake_context))

    adapter.apply_changes(plan, confirmed=True)

    assert fake_context.closed is True
    assert fake_p.stopped is True


def test_decode_job_id_from_a_real_shaped_url():
    # Verified live: this exact base64 segment decodes to {"jobId":
    # 12047884, "source": "gupy_portal"}.
    url = "https://globo.gupy.io/job/eyJqb2JJZCI6MTIwNDc4ODQsInNvdXJjZSI6Imd1cHlfcG9ydGFsIn0=?jobBoardSource=gupy_portal"

    assert _decode_job_id(url) == "12047884"


def test_decode_job_id_none_for_malformed_input():
    assert _decode_job_id("https://globo.gupy.io/job/not-valid-base64!!!") is None
    assert _decode_job_id("https://globo.gupy.io/job/") is None


def test_card_to_job_listing_converts_a_real_shaped_card():
    card = {
        "href": "https://globo.gupy.io/job/eyJqb2JJZCI6MTIwNDc4ODQsInNvdXJjZSI6Imd1cHlfcG9ydGFsIn0=?jobBoardSource=gupy_portal",
        "title": "Analista de Dados Pleno - Data & AI",
        "company": "Globo",
        "location": "Rio de Jan... - RJ",
    }

    listing = _card_to_job_listing(card)

    assert listing.site_name == "gupy"
    assert listing.external_id == "12047884"
    assert listing.company == "Globo"
    assert listing.url == card["href"]


def test_card_to_job_listing_none_when_title_missing_or_id_undecodable():
    assert _card_to_job_listing({"href": "https://x.gupy.io/job/abc", "title": None}) is None
    assert _card_to_job_listing({"href": "https://x.gupy.io/job/not-valid!!!", "title": "X"}) is None


class FakeSearchPage:
    def __init__(self, cards: list[dict]):
        # Accepts either a flat list of card dicts (single page, wrapped
        # here) or a list of pages (list of lists) for pagination tests.
        self._pages = [cards] if not cards or isinstance(cards[0], dict) else cards
        self.goto_calls = []
        self._evaluate_calls = 0

    def goto(self, url, timeout=None, wait_until=None):
        self.goto_calls.append(url)

    def wait_for_timeout(self, ms):
        pass

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


def test_search_jobs_builds_the_real_query_url_and_converts_valid_cards(monkeypatch):
    cards = [
        {
            "href": "https://globo.gupy.io/job/eyJqb2JJZCI6MTIwNDc4ODQsInNvdXJjZSI6Imd1cHlfcG9ydGFsIn0=",
            "title": "Analista de Dados",
            "company": "Globo",
            "location": "Rio de Janeiro - RJ",
        },
        {"href": "https://x.gupy.io/job/abc", "title": None, "company": None, "location": None},
    ]
    page = FakeSearchPage(cards)
    monkeypatch.setattr(
        session, "open_context", lambda site_name, *, headless: (FakeSearchPlaywright(), FakeSearchContext(page))
    )

    listings = GupyAdapter().search_jobs("Analista de Dados")

    assert len(listings) == 1
    assert listings[0].external_id == "12047884"
    # Page 1 has cards (fewer than max_results), so it pages on to 2 --
    # which comes back empty (real end of results) and stops there.
    assert page.goto_calls == [
        "https://portal.gupy.io/job-search/term=Analista%20de%20Dados",
        "https://portal.gupy.io/job-search/term=Analista%20de%20Dados?page=2",
    ]
