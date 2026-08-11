import json
from pathlib import Path

import pytest

from jarvis import config
from jarvis.resume.schema import Bilingual, PersonalInfo, Resume
from jarvis.sites import session
from jarvis.sites.base import PlannedFieldChange, SessionStatus, SiteProfileSnapshot, UpdatePlan
from jarvis.sites.infojobs import (
    InfoJobsAdapter,
    _is_authenticated,
    _map_resume_to_infojobs_fields,
    _parse_phone,
    _split_full_name,
)


def make_resume(**personal_info_overrides) -> Resume:
    defaults = {
        "full_name": "Nicholas Birochi",
        "phone": "+55 (11) 95827-5250",
        "email": "nicholas@example.com",
    }
    defaults.update(personal_info_overrides)
    return Resume(
        personal_info=PersonalInfo(**defaults),
        summary=Bilingual(pt="Resumo em português."),
    )


def test_parse_phone_splits_area_code_and_number():
    # Verified live against the real account: "+55 (11) 95827-5250" ->
    # txtPhone1Code="11", txtPhone1="958275250".
    assert _parse_phone("+55 (11) 95827-5250") == ("11", "958275250")


def test_parse_phone_without_country_code():
    assert _parse_phone("(11) 95827-5250") == ("11", "958275250")


def test_parse_phone_none():
    assert _parse_phone(None) == (None, None)


def test_split_full_name():
    assert _split_full_name("Nicholas Birochi") == ("Nicholas", "Birochi")
    assert _split_full_name("Nicholas Silva Birochi") == ("Nicholas", "Silva Birochi")
    assert _split_full_name("Cher") == ("Cher", "")


def test_map_resume_to_infojobs_fields():
    resume = make_resume()

    fields = _map_resume_to_infojobs_fields(resume)

    # Email isn't part of this mapping at all -- it's not on the InfoJobs
    # edit form (see infojobs.py's module docstring), only name/phone are.
    assert fields == {
        "full_name": "Nicholas Birochi",
        "phone": "11 958275250",
    }
    assert "email" not in fields


class FakePage:
    """Stand-in for a Playwright Page -- just enough of input_value() to
    exercise _scrape_profile_fields without a real browser."""

    def __init__(self, values: dict[str, str]):
        self._values = values

    def input_value(self, selector: str) -> str:
        return self._values[selector]


def test_scrape_profile_fields_combines_name_surname_and_phone():
    page = FakePage(
        {
            "#ctl00_phMasterPage_cPersonalData_txtName": "Nicholas",
            "#ctl00_phMasterPage_cPersonalData_txtSurname": "Birochi",
            "#ctl00_phMasterPage_cPersonalData_txtPhone1Code": "11",
            "#ctl00_phMasterPage_cPersonalData_txtPhone1": "958275250",
        }
    )
    adapter = InfoJobsAdapter()

    fields = adapter._scrape_profile_fields(page)

    assert fields == {
        "full_name": "Nicholas Birochi",
        "phone": "11 958275250",
    }


def test_build_update_plan_only_includes_differing_fields():
    resume = make_resume()
    current = SiteProfileSnapshot(
        site_name="infojobs",
        fields={
            "full_name": "Nicholas Birochi",  # same -- no change needed
            "phone": "11 999999999",  # different -- change needed
        },
    )
    adapter = InfoJobsAdapter()

    plan = adapter.build_update_plan(resume, current)

    assert plan.site_name == "infojobs"
    assert {c.site_field for c in plan.changes} == {"phone"}


def test_build_update_plan_empty_when_nothing_differs():
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="infojobs", fields=_map_resume_to_infojobs_fields(resume))
    adapter = InfoJobsAdapter()

    plan = adapter.build_update_plan(resume, current)

    assert plan.changes == []


def test_build_update_plan_skips_fields_missing_locally():
    resume = make_resume(phone=None)
    current = SiteProfileSnapshot(
        site_name="infojobs",
        fields={**_map_resume_to_infojobs_fields(resume), "phone": "11 999999999"},
    )
    adapter = InfoJobsAdapter()

    plan = adapter.build_update_plan(resume, current)

    assert plan.changes == []


def test_preview_changes_reports_no_changes():
    adapter = InfoJobsAdapter()
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="infojobs", fields=_map_resume_to_infojobs_fields(resume))
    plan = adapter.build_update_plan(resume, current)

    preview = adapter.preview_changes(plan)

    assert "Nenhuma mudança" in preview.summary_text


def test_preview_changes_lists_each_change():
    adapter = InfoJobsAdapter()
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="infojobs", fields={"phone": "11 999999999"})
    plan = adapter.build_update_plan(resume, current)

    preview = adapter.preview_changes(plan)

    assert "phone" in preview.summary_text
    assert "11 958275250" in preview.summary_text
    assert "personal_info.phone" in preview.summary_text


def test_apply_changes_refuses_without_confirmation():
    adapter = InfoJobsAdapter()
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="infojobs", fields={"phone": "11 999999999"})
    plan = adapter.build_update_plan(resume, current)

    result = adapter.apply_changes(plan, confirmed=False)

    assert result.applied is False
    assert "confirmed=True" in result.error


def test_apply_changes_succeeds_trivially_with_no_changes_even_if_confirmed():
    adapter = InfoJobsAdapter()
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="infojobs", fields=_map_resume_to_infojobs_fields(resume))
    plan = adapter.build_update_plan(resume, current)

    result = adapter.apply_changes(plan, confirmed=True)

    assert result.applied is True
    assert result.changes_applied == []


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
    monkeypatch.setattr(config, "INFOJOBS_LOGIN_URL", "https://login.infojobs.com.br/Account/Login")
    page = FakeAuthPage(final_url="https://www.infojobs.com.br/candidate/curriculum")

    assert _is_authenticated(FakeAuthContext(page)) is True
    assert page.closed is True  # page is cleaned up either way


def test_is_authenticated_false_when_still_on_login_page(monkeypatch):
    monkeypatch.setattr(config, "INFOJOBS_LOGIN_URL", "https://login.infojobs.com.br/Account/Login")
    page = FakeAuthPage(final_url="https://login.infojobs.com.br/Account/Login")

    assert _is_authenticated(FakeAuthContext(page)) is False


def test_check_session_not_logged_in_without_a_saved_session(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SITES_STATE_DIR", tmp_path)

    assert InfoJobsAdapter().check_session() == SessionStatus.NOT_LOGGED_IN


def test_apply_changes_refuses_entire_plan_if_any_field_unsupported(monkeypatch):
    # A plan mixing a supported field (phone) with an unsupported one must
    # refuse the whole thing, not silently write part of it -- same
    # precedent as Gupy's equivalent guard.
    def _fail_open_context(site_name, *, headless):
        raise AssertionError("should not open a browser session when any field is unsupported")

    monkeypatch.setattr(session, "open_context", _fail_open_context)

    adapter = InfoJobsAdapter()
    plan = UpdatePlan(
        site_name="infojobs",
        changes=[
            PlannedFieldChange(
                site_field="phone",
                current_value="11 900000000",
                new_value="11 988888888",
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

    def on(self, event, handler):
        pass  # no dialog fires in these fakes -- see FakeBlockingDialogPage below for that case

    def goto(self, url, timeout=None, wait_until=None):
        pass

    def reload(self, wait_until=None, timeout=None):
        pass

    def wait_for_timeout(self, ms):
        pass

    def fill(self, selector, value):
        if self.apply_fills:
            self.values[selector] = value

    def input_value(self, selector):
        return self.values[selector]

    def query_selector(self, selector):
        if selector == "a.js_btSend":
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
        "#ctl00_phMasterPage_cPersonalData_txtName": "Nicholas",
        "#ctl00_phMasterPage_cPersonalData_txtSurname": "Birochi",
        "#ctl00_phMasterPage_cPersonalData_txtPhone1Code": "11",
        "#ctl00_phMasterPage_cPersonalData_txtPhone1": "900000000",
    }
    values.update(overrides)
    return values


def test_apply_changes_writes_phone_and_full_name_when_supported(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SITES_EVIDENCE_DIR", tmp_path / "evidence")
    resume = make_resume(full_name="Nicholas Silva", phone="+55 (11) 98888-8888")
    current = SiteProfileSnapshot(
        site_name="infojobs",
        fields={"full_name": "Nicholas Birochi", "phone": "11 900000000"},
    )
    adapter = InfoJobsAdapter()
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
    assert page.values["#ctl00_phMasterPage_cPersonalData_txtName"] == "Nicholas"
    assert page.values["#ctl00_phMasterPage_cPersonalData_txtSurname"] == "Silva"
    assert page.values["#ctl00_phMasterPage_cPersonalData_txtPhone1Code"] == "11"
    assert page.values["#ctl00_phMasterPage_cPersonalData_txtPhone1"] == "988888888"
    assert result.evidence_path is not None

    # Evidence is a small JSON audit record, deliberately NOT a screenshot --
    # this same page also shows CPF/birth date, which a screenshot would
    # capture incidentally even though the write itself never touches them.
    evidence = json.loads(Path(result.evidence_path).read_text(encoding="utf-8"))
    assert evidence["site_name"] == "infojobs"
    assert {c["field"] for c in evidence["changes"]} == {"full_name", "phone"}


def test_apply_changes_reports_failure_if_site_does_not_reflect_change(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SITES_EVIDENCE_DIR", tmp_path / "evidence")
    resume = make_resume(phone="+55 (11) 98888-8888")
    current = SiteProfileSnapshot(
        site_name="infojobs", fields={**_map_resume_to_infojobs_fields(resume), "phone": "11 900000000"}
    )
    adapter = InfoJobsAdapter()
    plan = adapter.build_update_plan(resume, current)

    page = FakeApplyPage(_base_profile_values(), apply_fills=False)
    monkeypatch.setattr(
        session, "open_context", lambda site_name, *, headless: (FakeApplyPlaywright(), FakeApplyContext(page))
    )

    result = adapter.apply_changes(plan, confirmed=True)

    assert result.applied is False
    assert "phone" in result.error
    assert page.save_button.clicked is True  # it did try to save


class FakeSilentSaveApplyPage(FakeApplyPage):
    """Reproduces the real, live-confirmed InfoJobs bug: clicking "SALVAR
    CV" does nothing server-side, but the <input> elements still hold
    whatever page.fill() wrote to them since nothing reloaded the DOM. A
    verify step that re-scrapes WITHOUT reloading first would see its own
    fill() and wrongly report success -- reload() resets to the
    pre-save values here, standing in for the real server's unchanged
    state."""

    def __init__(self, saved_values: dict[str, str]):
        super().__init__(saved_values)
        self._server_values = dict(saved_values)

    def reload(self, wait_until=None, timeout=None):
        self.values = dict(self._server_values)


def test_apply_changes_catches_a_save_click_that_never_reaches_the_server(monkeypatch, tmp_path):
    # The real bug found live on 2026-08-11: clicking a.js_btSend fired zero
    # requests to infojobs.com.br, yet the unreloaded DOM still showed the
    # locally-filled value. Without a reload before re-scraping, apply_changes
    # would falsely report success.
    monkeypatch.setattr(config, "SITES_EVIDENCE_DIR", tmp_path / "evidence")
    resume = make_resume(phone="+55 (11) 98888-8888")
    current = SiteProfileSnapshot(
        site_name="infojobs", fields={**_map_resume_to_infojobs_fields(resume), "phone": "11 900000000"}
    )
    adapter = InfoJobsAdapter()
    plan = adapter.build_update_plan(resume, current)

    page = FakeSilentSaveApplyPage(_base_profile_values())
    monkeypatch.setattr(
        session, "open_context", lambda site_name, *, headless: (FakeApplyPlaywright(), FakeApplyContext(page))
    )

    result = adapter.apply_changes(plan, confirmed=True)

    assert result.applied is False
    assert "phone" in result.error


class FakeDialog:
    def __init__(self, message: str):
        self.message = message
        self.dismissed = False

    def dismiss(self):
        self.dismissed = True


class _DialogFiringSaveButton(FakeSaveButton):
    def __init__(self, page: "FakeBlockingDialogPage"):
        super().__init__()
        self._page = page

    def click(self):
        super().click()
        if self._page.dialog_handler is not None:
            self._page.dialog_handler(FakeDialog(self._page.dialog_message))


class FakeBlockingDialogPage(FakeApplyPage):
    """Reproduces the real, live-confirmed InfoJobs bug: an unrelated empty
    required field elsewhere on the page (Preferências > Área de Atuação)
    makes the site's own client-side validation call alert(...) and bail
    out before the save ever reaches the server -- see infojobs.py's
    module docstring. save_button.click() here fires the same dialog a
    real browser would, exactly like the site's own JS does before it
    would otherwise click the real, separate submit trigger."""

    def __init__(self, values: dict[str, str], dialog_message: str):
        super().__init__(values)
        self.dialog_message = dialog_message
        self.dialog_handler = None
        self.save_button = _DialogFiringSaveButton(self)

    def on(self, event, handler):
        if event == "dialog":
            self.dialog_handler = handler


def test_apply_changes_surfaces_the_real_validation_alert_instead_of_a_vague_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SITES_EVIDENCE_DIR", tmp_path / "evidence")
    resume = make_resume(phone="+55 (11) 98888-8888")
    current = SiteProfileSnapshot(
        site_name="infojobs", fields={**_map_resume_to_infojobs_fields(resume), "phone": "11 900000000"}
    )
    adapter = InfoJobsAdapter()
    plan = adapter.build_update_plan(resume, current)

    page = FakeBlockingDialogPage(_base_profile_values(), dialog_message="Revise os campos em vermelho.")
    monkeypatch.setattr(
        session, "open_context", lambda site_name, *, headless: (FakeApplyPlaywright(), FakeApplyContext(page))
    )

    result = adapter.apply_changes(plan, confirmed=True)

    assert result.applied is False
    assert "Revise os campos em vermelho." in result.error
    assert "Preferências" in result.error  # points at the real, known culprit, not a vague "confira manualmente"


def test_apply_changes_reports_missing_save_button(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SITES_EVIDENCE_DIR", tmp_path / "evidence")
    resume = make_resume(phone="+55 (11) 98888-8888")
    current = SiteProfileSnapshot(
        site_name="infojobs", fields={**_map_resume_to_infojobs_fields(resume), "phone": "11 900000000"}
    )
    adapter = InfoJobsAdapter()
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
    resume = make_resume(phone="+55 (11) 98888-8888")
    current = SiteProfileSnapshot(
        site_name="infojobs", fields={**_map_resume_to_infojobs_fields(resume), "phone": "11 900000000"}
    )
    adapter = InfoJobsAdapter()
    plan = adapter.build_update_plan(resume, current)

    page = FakeApplyPage(_base_profile_values())
    fake_context = FakeApplyContext(page)
    fake_p = FakeApplyPlaywright()
    monkeypatch.setattr(session, "open_context", lambda site_name, *, headless: (fake_p, fake_context))

    adapter.apply_changes(plan, confirmed=True)

    assert fake_context.closed is True
    assert fake_p.stopped is True
