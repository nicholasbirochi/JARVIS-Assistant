import json
from pathlib import Path

import pytest

from jarvis import config
from jarvis.resume.schema import Bilingual, PersonalInfo, Resume
from jarvis.sites import session
from jarvis.sites.base import PlannedFieldChange, SiteProfileSnapshot, UpdatePlan
from jarvis.sites import application_profile
from jarvis.sites.gupy import (
    GupyAdapter,
    _card_to_job_listing,
    _clean_question_id,
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


def test_extract_company_from_gate_text_parses_the_real_pattern():
    text = "Você está se candidatando para a vaga Trainee Itaú Unibanco 2027 na empresa Itaú Unibanco."

    assert GupyAdapter._extract_company_from_gate_text(text) == "Itaú Unibanco"


def test_extract_company_from_gate_text_none_when_pattern_does_not_match():
    assert GupyAdapter._extract_company_from_gate_text("Texto qualquer sem o padrão esperado") is None


# --- preview_application() ---------------------------------------------
#
# Shapes real, live-confirmed script content (see gupy.py's module
# docstring): _get_apply_href's script mentions "apply-link";
# _extract_step_text's mentions "innerText"; _answer_referral_labels'
# mentions "querySelectorAll('label')"; _extract_company_questions'
# mentions "main h3, body h3"; _click_text_button's embeds the target
# text as a Python repr() (e.g. 'Continuar') -- FakeApplicationPage
# dispatches on those same markers instead of guessing at exact JS.


class FakeApplicationPage:
    def __init__(self, *, apply_href="/candidates/jobs/123/apply", step_texts, referral_answer_count=0,
                 click_results=None, company_questions=None, fill_selectors=None,
                 page_title="Página da Vaga | Analista de Dados"):
        self.apply_href = apply_href
        self.url = "https://empresa.gupy.io/job/xyz"
        self.step_texts = step_texts
        self._step_text_idx = 0
        self.referral_answer_count = referral_answer_count
        self.click_results = click_results or {}
        self.company_questions = company_questions or []
        self.clicked: list[str] = []
        self.fill_selectors = fill_selectors  # None = every selector succeeds
        self.filled: dict[str, str] = {}
        self._page_title = page_title
        self.last_is_referred = None

    def goto(self, url, timeout=None, wait_until=None):
        self.url = url

    def title(self):
        return self._page_title

    def wait_for_load_state(self, state, timeout=None):
        pass

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script, *args):
        if "apply-link" in script:
            return self.apply_href
        if "main h3, body h3" in script:
            return self.company_questions
        if "innerText" in script:
            text = self.step_texts[self._step_text_idx]
            self._step_text_idx = min(self._step_text_idx + 1, len(self.step_texts) - 1)
            return text
        if "querySelectorAll('label')" in script:
            if args:
                self.last_is_referred = args[0]
            return self.referral_answer_count
        for text, result in self.click_results.items():
            if repr(text) in script:
                if result:
                    self.clicked.append(text)
                return result
        return False

    def fill(self, selector, value, timeout=None):
        # fill_selectors: set by tests to the selectors that should
        # succeed ({} means every selector "works", matching real
        # Playwright raising only when the element genuinely isn't
        # found -- tests that want a failure set fill_selectors
        # explicitly to a smaller allow-list).
        if self.fill_selectors is not None and selector not in self.fill_selectors:
            raise Exception(f"no element matching {selector!r}")
        self.filled[selector] = value


class FakeApplicationContext:
    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_page(self):
        return self._page

    def close(self):
        self.closed = True


class FakeApplicationPlaywright:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def _patch_open_context(monkeypatch, page):
    monkeypatch.setattr(
        session, "open_context", lambda site_name, *, headless: (FakeApplicationPlaywright(), FakeApplicationContext(page))
    )


def test_preview_application_blocked_when_apply_link_is_missing(monkeypatch):
    page = FakeApplicationPage(apply_href=None, step_texts=[""])
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().preview_application("https://empresa.gupy.io/job/xyz")

    assert preview.can_submit is False
    assert "Candidatar-se" in preview.blocked_reason
    assert preview.questions == []


def test_preview_application_answers_referral_then_stops_at_company_questions_with_pii(monkeypatch):
    # Shapes the real Itaú pilot, 2026-08-12: referral questions answered
    # automatically, then a company-specific question step asking for RG
    # -- must stop, never fabricate an answer, and be flagged as hard PII
    # specifically (not just "sensitive").
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão\nVocê trabalha na empresa?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Qual é o seu RG?\nResponder agora",
        ],
        referral_answer_count=2,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Qual é o seu RG?"],
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().preview_application("https://empresa.gupy.io/job/xyz")

    assert preview.can_submit is False
    assert "documento oficial" in preview.blocked_reason
    assert len(preview.questions) == 2
    assert preview.questions[0].answered is True
    assert preview.questions[0].answer == "Não (para todas)"
    assert preview.questions[1].answered is False
    assert preview.questions[1].is_hard_pii is True
    assert "Continuar" in page.clicked
    assert "Responder agora" in page.clicked


def test_preview_application_stops_at_company_questions_even_without_pii_terms(monkeypatch):
    # The broader rule: ANY company-specific question is a stop, not just
    # ones that hit the PII/financial blocklist -- see base.py's
    # question_requires_stop() docstring. Not flagged as hard PII either.
    # (2026-08-21: this test previously used "Você tem CNH?" as its
    # example of an unclassified question -- it became a real, classified
    # field the same day, which would have silently flipped this
    # assertion into the OTHER blocking bucket. Using a genuinely
    # subjective/unclassified question instead.)
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Qual seu nível de conhecimento em Python?\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Qual seu nível de conhecimento em Python?"],
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().preview_application("https://empresa.gupy.io/job/xyz")

    assert preview.can_submit is False
    assert "não responde nenhuma pergunta específica" in preview.blocked_reason
    assert preview.questions[-1].is_hard_pii is False


def test_preview_application_flags_sensitive_non_pii_questions_distinctly(monkeypatch):
    # Real, confirmed live 2026-08-13 (BIP Brasil): a salary-expectation
    # question is sensitive but NOT a government-ID question -- the
    # reason shown must reflect that distinction, not lump it with RG/CPF.
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Qual sua pretensão salarial atual?\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Qual sua pretensão salarial atual?"],
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().preview_application("https://empresa.gupy.io/job/xyz")

    assert preview.can_submit is False
    assert "dado sensível" in preview.blocked_reason
    assert "documento oficial" not in preview.blocked_reason
    assert preview.questions[-1].is_hard_pii is False


def test_preview_application_never_claims_can_submit_even_with_no_company_questions(monkeypatch):
    # Real, deliberate limitation: the final submit screen has never been
    # observed live (every real listing tested stopped earlier), so
    # can_submit must stay False even in the "clean" case rather than
    # inventing a button to click.
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Tudo certo, revise sua candidatura.",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True},
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().preview_application("https://empresa.gupy.io/job/xyz")

    assert preview.can_submit is False
    assert "nunca foi verificado" in preview.blocked_reason


def test_preview_application_never_fills_or_saves_a_real_referral_contact(monkeypatch):
    # Real incident, 2026-08-19: this exact gap let preview_application()
    # (documented as "never fills in answers from the local profile")
    # actually fill AND SAVE a real referral contact's name/email
    # whenever the company matched one, because that logic lived in the
    # shared _start_application() with no gate of its own. Nicholas's
    # own Gupy dashboard showed a real, saved candidatura for "Fundação
    # Itaú" with progress, created purely by preview/investigation
    # calls. This is the regression test that should have existed
    # before that ever happened.
    contact = {"name": "Ana Beatriz Ferreira", "email": "ana.ferreira@itau-unibanco.com.br"}
    monkeypatch.setattr(application_profile, "load_referral_contacts", lambda: {"itau": contact})

    page = FakeApplicationPage(
        step_texts=[
            "Você está se candidatando para a vaga Trainee 2027 na empresa Itaú Unibanco.",
            "Alguém te indicou?\nSim\nNão",
            "Tudo certo, revise sua candidatura.",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True},
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().preview_application("https://empresa.gupy.io/job/xyz")

    # The real, load-bearing assertions: no contact field was ever
    # touched, and the referral question was answered "Não" even though
    # a real, known contact exists for this company.
    assert page.filled == {}
    assert page.last_is_referred is False
    referral_question = preview.questions[0]
    assert referral_question.answer == "Não (para todas)"
    assert contact["name"] not in (preview.summary_text or "")
    assert contact["email"] not in (preview.summary_text or "")


def test_preview_application_closes_context_and_stops_playwright(monkeypatch):
    page = FakeApplicationPage(step_texts=["algo"], referral_answer_count=0)
    fake_context = FakeApplicationContext(page)
    fake_p = FakeApplicationPlaywright()
    monkeypatch.setattr(session, "open_context", lambda site_name, *, headless: (fake_p, fake_context))

    GupyAdapter().preview_application("https://empresa.gupy.io/job/xyz")

    assert fake_context.closed is True
    assert fake_p.stopped is True


# --- _clean_question_id() / _fill_company_answer() ----------------------
#
# Real, confirmed-live inconsistency found 2026-08-19 (Integra CSC,
# during a supervised investigation): that listing's real input id was
# "input-Qual sua pretensão salarial?" -- no "N. " numbering prefix, no
# trailing whitespace/required-marker -- unlike the still-real
# 2026-08-13 BIP Brasil case (full, still-numbered question text used
# as-is). This is the real bug a supervised test caught: the original
# selector never matched this listing's real DOM at all, so the fill
# silently failed and nothing advanced.


def test_clean_question_id_strips_numbering_and_trailing_marker():
    assert _clean_question_id("1. Qual sua pretensão salarial? \xa0*") == "Qual sua pretensão salarial?"
    assert _clean_question_id("12. Você tem CNH?*") == "Você tem CNH?"


def test_clean_question_id_no_op_when_already_clean():
    assert _clean_question_id("Qual sua pretensão salarial?") == "Qual sua pretensão salarial?"


def test_fill_company_answer_tries_the_raw_text_selector_first():
    page = FakeApplicationPage(
        step_texts=["algo"],
        fill_selectors={'[id="input-1. Qual sua pretensão salarial? \xa0*"]'},
    )

    ok = GupyAdapter()._fill_company_answer(page, "1. Qual sua pretensão salarial? \xa0*", "R$ 4.500,00")

    assert ok is True
    assert page.filled == {'[id="input-1. Qual sua pretensão salarial? \xa0*"]': "R$ 4.500,00"}


def test_fill_company_answer_falls_back_to_the_cleaned_id_real_integracsc_case():
    # The real, live-confirmed case that exposed this bug -- only the
    # CLEANED selector exists on this listing's real DOM.
    page = FakeApplicationPage(
        step_texts=["algo"],
        fill_selectors={'[id="input-Qual sua pretensão salarial?"]'},
    )

    ok = GupyAdapter()._fill_company_answer(page, "1. Qual sua pretensão salarial? \xa0*", "R$ 6.500,00")

    assert ok is True
    assert page.filled == {'[id="input-Qual sua pretensão salarial?"]': "R$ 6.500,00"}


def test_fill_company_answer_fails_closed_when_neither_selector_matches():
    page = FakeApplicationPage(step_texts=["algo"], fill_selectors=set())

    ok = GupyAdapter()._fill_company_answer(page, "1. Qual sua pretensão salarial? \xa0*", "R$ 4.500,00")

    assert ok is False
    assert page.filled == {}


# --- continue_application_with_profile() --------------------------------


def _patch_profile(monkeypatch, **fields):
    from jarvis.sites import application_profile

    full = {
        "rg": None,
        "rg_orgao_estado": None,
        "cpf": None,
        "nome_mae": None,
        "nome_pai": None,
        "naturalidade": None,
        "raca_cor": None,
        "pcd": None,
        "salary_estagio": None,
        "salary_junior": None,
        "salary_pleno": None,
        "marital_status": None,
        "cnh": None,
        "disponibilidade_viagem": None,
        "disponibilidade_fds": None,
        "escolaridade": None,
        "disponibilidade_inicio_imediato": None,
        "cargo_atual": None,
        "parentes_na_empresa": None,
        "semestre_formatura": None,
        "nome_completo": None,
    }
    full.update(fields)
    monkeypatch.setattr(application_profile, "load_application_profile", lambda: full)


def test_continue_application_with_profile_refuses_without_confirmed(monkeypatch):
    _patch_profile(monkeypatch)
    page = FakeApplicationPage(step_texts=["algo"])
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=False)

    assert preview.can_submit is False
    assert "confirmed=True" in preview.blocked_reason
    assert page.clicked == []  # never even started navigating


def test_continue_application_with_profile_refuses_when_a_question_has_no_local_value(monkeypatch):
    # Salary question exists, but the local profile has nothing for it --
    # must refuse the WHOLE step, not fill nothing and half-advance.
    _patch_profile(monkeypatch)  # everything None
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Qual sua pretensão salarial atual?\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Qual sua pretensão salarial atual?"],
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert preview.can_submit is False
    assert "tudo ou nada" in preview.blocked_reason
    assert page.filled == {}  # nothing was actually typed into the page
    assert preview.questions[-1].answered is False


def test_continue_application_with_profile_refuses_for_an_unclassified_question(monkeypatch):
    _patch_profile(monkeypatch, salary_junior="R$ 4.500,00")
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Você tem CNH?\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Você tem CNH?"],
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert preview.can_submit is False
    assert page.filled == {}


def test_continue_application_with_profile_fills_all_known_questions_and_advances(monkeypatch):
    _patch_profile(monkeypatch, salary_junior="R$ 4.500,00")
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Qual sua pretensão salarial atual?\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Qual sua pretensão salarial atual?"],
        fill_selectors={'[id="input-1.Qual sua pretensão salarial atual?"]'},
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert page.filled == {'[id="input-1.Qual sua pretensão salarial atual?"]': "R$ 4.500,00"}
    # finalize=False (default) -- stops right after saving, never
    # submitted, even though finalize=True has since been verified live
    # to work for other calls.
    assert preview.can_submit is False
    assert preview.submitted is False
    assert "não pedi pra enviar de verdade" in preview.blocked_reason
    assert preview.questions[-1].answered is True


# --- continue_application_with_profile(finalize=True) --------------------
#
# 2026-08-19, human-supervised, real, confirmed live (Integra CSC,
# Nicholas explicitly said "Eu quero que finalize!") -- the real
# "Finalizar candidatura" button and its real "Candidatura finalizada!"
# confirmation text, shaping these fakes.


def test_continue_application_with_profile_finalize_true_submits_and_confirms(monkeypatch):
    _patch_profile(monkeypatch, salary_junior="R$ 4.500,00")
    page = FakeApplicationPage(
        # Four distinct step_texts, one per real _extract_step_text()
        # call in order: gate, referral, company-questions-step check,
        # post-finalize confirmation.
        step_texts=[
            "Você está se candidatando para a vaga X na empresa Y.",
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Qual sua pretensão salarial atual?\nResponder agora",
            "Candidatura finalizada!\n\nAgora a empresa vai analisar sua compatibilidade.",
        ],
        referral_answer_count=1,
        click_results={
            "Continuar": True,
            "Salvar e continuar": True,
            "Responder agora": True,
            "Finalizar candidatura": True,
        },
        company_questions=["1.Qual sua pretensão salarial atual?"],
        fill_selectors={'[id="input-1.Qual sua pretensão salarial atual?"]'},
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile(
        "https://empresa.gupy.io/job/xyz", confirmed=True, finalize=True
    )

    assert preview.can_submit is True
    assert preview.submitted is True
    assert preview.blocked_reason is None
    assert "Finalizar candidatura" in page.clicked


def test_continue_application_with_profile_finalize_true_without_real_confirmation_is_not_success(monkeypatch):
    # Clicked the button, but the resulting screen didn't actually say
    # "Candidatura finalizada" -- must NOT be reported as a success.
    _patch_profile(monkeypatch, salary_junior="R$ 4.500,00")
    page = FakeApplicationPage(
        step_texts=[
            "Você está se candidatando para a vaga X na empresa Y.",
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Qual sua pretensão salarial atual?\nResponder agora",
            "Algo inesperado aconteceu.",
        ],
        referral_answer_count=1,
        click_results={
            "Continuar": True,
            "Salvar e continuar": True,
            "Responder agora": True,
            "Finalizar candidatura": True,
        },
        company_questions=["1.Qual sua pretensão salarial atual?"],
        fill_selectors={'[id="input-1.Qual sua pretensão salarial atual?"]'},
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile(
        "https://empresa.gupy.io/job/xyz", confirmed=True, finalize=True
    )

    assert preview.can_submit is False
    assert preview.submitted is False
    assert "não mostrou a" in preview.blocked_reason


def test_continue_application_with_profile_finalize_true_button_not_found(monkeypatch):
    _patch_profile(monkeypatch, salary_junior="R$ 4.500,00")
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Qual sua pretensão salarial atual?\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={
            "Continuar": True,
            "Salvar e continuar": True,
            "Responder agora": True,
            "Finalizar candidatura": False,
        },
        company_questions=["1.Qual sua pretensão salarial atual?"],
        fill_selectors={'[id="input-1.Qual sua pretensão salarial atual?"]'},
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile(
        "https://empresa.gupy.io/job/xyz", confirmed=True, finalize=True
    )

    assert preview.can_submit is False
    assert preview.submitted is False
    assert "não encontrei o botão" in preview.blocked_reason


def test_continue_application_with_profile_finalize_false_never_looks_for_the_button(monkeypatch):
    # Default behavior must be unchanged -- no attempt to click
    # "Finalizar candidatura" at all when finalize isn't requested.
    _patch_profile(monkeypatch, salary_junior="R$ 4.500,00")
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Qual sua pretensão salarial atual?\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Qual sua pretensão salarial atual?"],
        fill_selectors={'[id="input-1.Qual sua pretensão salarial atual?"]'},
    )
    _patch_open_context(monkeypatch, page)

    GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert "Finalizar candidatura" not in page.clicked
    assert "Salvar e continuar" in page.clicked


def test_continue_application_with_profile_uses_the_pleno_salary_for_a_pleno_listing(monkeypatch):
    # Real case found live 2026-08-17 ("Engenheiro de Dados Pl."):
    # "pretensão salarial" must resolve to salary_pleno, not
    # salary_junior, when the JOB LISTING itself (not the question) is
    # pleno-level.
    _patch_profile(monkeypatch, salary_junior="R$ 4.500,00", salary_pleno="R$ 6.500,00")
    page = FakeApplicationPage(
        page_title="Página da Vaga | Engenheiro de Dados Pl.",
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Qual sua pretensão salarial atual?\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Qual sua pretensão salarial atual?"],
        fill_selectors={'[id="input-1.Qual sua pretensão salarial atual?"]'},
    )
    _patch_open_context(monkeypatch, page)

    GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert page.filled == {'[id="input-1.Qual sua pretensão salarial atual?"]': "R$ 6.500,00"}


def test_continue_application_with_profile_uses_the_estagio_salary_for_an_internship(monkeypatch):
    _patch_profile(monkeypatch, salary_estagio="R$ 3.000,00", salary_junior="R$ 4.500,00")
    page = FakeApplicationPage(
        page_title="Página da Vaga | Estágio em Análise de Dados",
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Qual sua pretensão salarial atual?\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Qual sua pretensão salarial atual?"],
        fill_selectors={'[id="input-1.Qual sua pretensão salarial atual?"]'},
    )
    _patch_open_context(monkeypatch, page)

    GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert page.filled == {'[id="input-1.Qual sua pretensão salarial atual?"]': "R$ 3.000,00"}


def test_continue_application_with_profile_reports_a_fill_failure(monkeypatch):
    _patch_profile(monkeypatch, salary_junior="R$ 4.500,00")
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Qual sua pretensão salarial atual?\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Qual sua pretensão salarial atual?"],
        fill_selectors=set(),  # every fill() call fails -- selector not found
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert preview.can_submit is False
    assert preview.questions[-1].answered is False
    assert "Confira manualmente" in preview.blocked_reason


def test_continue_application_with_profile_still_blocks_rg_even_when_provided(monkeypatch):
    # RG IS fillable now (explicitly confirmed 2026-08-13) -- this test
    # just confirms it fills like any other known field when a value
    # exists, rather than being silently excluded from the mechanism.
    _patch_profile(monkeypatch, rg="12.345.678-9")
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Qual é o seu RG?\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Qual é o seu RG?"],
        fill_selectors={'[id="input-1.Qual é o seu RG?"]'},
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert page.filled == {'[id="input-1.Qual é o seu RG?"]': "12.345.678-9"}
    assert "12.345.678-9" not in str(preview.questions[-1])
    assert "12.345.678-9" not in (preview.summary_text or "")


def test_continue_application_with_profile_still_refuses_birth_date_even_with_full_profile(monkeypatch):
    # No fillable field exists for birth date at all (see base.py) --
    # a fully-populated profile still can't answer this one.
    _patch_profile(monkeypatch, rg="12.345.678-9", cpf="123.456.789-00", salary_junior="5000", marital_status="Solteiro")
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Qual sua data de nascimento?\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Qual sua data de nascimento?"],
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert preview.can_submit is False
    assert page.filled == {}


def test_continue_application_with_profile_answers_ja_trabalhou_aqui_without_any_local_value(monkeypatch):
    # 2026-08-21: "ja_trabalhou_aqui" always resolves to "Não" -- never
    # needs a real .env value, same reasoning as the standard referral
    # question's own "você trabalha na empresa?".
    _patch_profile(monkeypatch)  # everything None, including ja_trabalhou_aqui
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Você já trabalhou nesta empresa?\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Você já trabalhou nesta empresa?"],
        fill_selectors={'[id="input-1.Você já trabalhou nesta empresa?"]'},
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert page.filled == {'[id="input-1.Você já trabalhou nesta empresa?"]': "Não"}
    assert preview.questions[-1].answered is True


def test_continue_application_with_profile_fills_linkedin_from_the_resume(monkeypatch):
    # 2026-08-21: "linkedin" comes from the résumé's own public links,
    # not the confidential .env profile -- it's already public data.
    from jarvis.resume import store as resume_store
    from jarvis.resume.schema import Bilingual, Links, PersonalInfo, Resume

    resume = Resume(
        personal_info=PersonalInfo(
            full_name="Nicholas Birochi",
            links=Links(linkedin="https://www.linkedin.com/in/nicholasbirochi/"),
        ),
        summary=Bilingual(pt="Resumo."),
    )
    monkeypatch.setattr(resume_store, "load", lambda: resume)

    _patch_profile(monkeypatch)  # linkedin is None in the .env-backed profile
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Compartilhe o link do seu LinkedIn:\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Compartilhe o link do seu LinkedIn:"],
        fill_selectors={'[id="input-1.Compartilhe o link do seu LinkedIn:"]'},
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert page.filled == {
        '[id="input-1.Compartilhe o link do seu LinkedIn:"]': "https://www.linkedin.com/in/nicholasbirochi/"
    }
    assert preview.questions[-1].answered is True


def test_continue_application_with_profile_refuses_linkedin_question_when_resume_has_none(monkeypatch):
    from jarvis.resume import store as resume_store
    from jarvis.resume.schema import Bilingual, PersonalInfo, Resume

    resume = Resume(personal_info=PersonalInfo(full_name="Nicholas Birochi"), summary=Bilingual(pt="Resumo."))
    monkeypatch.setattr(resume_store, "load", lambda: resume)

    _patch_profile(monkeypatch)
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Compartilhe o link do seu LinkedIn:\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Compartilhe o link do seu LinkedIn:"],
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert preview.can_submit is False
    assert page.filled == {}


def test_continue_application_with_profile_fills_disponibilidade_inicio_imediato_from_the_resume(monkeypatch):
    # 2026-08-21: resolved from job_preferences.availability.status,
    # only when it's explicitly "immediate" -- any other status is a
    # real, different answer this code must not guess at.
    from jarvis.resume import store as resume_store
    from jarvis.resume.schema import Availability, Bilingual, JobPreferences, PersonalInfo, Resume

    resume = Resume(
        personal_info=PersonalInfo(full_name="Nicholas Birochi"),
        summary=Bilingual(pt="Resumo."),
        job_preferences=JobPreferences(availability=Availability(status="immediate")),
    )
    monkeypatch.setattr(resume_store, "load", lambda: resume)

    _patch_profile(monkeypatch)
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Disponibilidade para início imediato?\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Disponibilidade para início imediato?"],
        fill_selectors={'[id="input-1.Disponibilidade para início imediato?"]'},
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert page.filled == {'[id="input-1.Disponibilidade para início imediato?"]': "Sim"}
    assert preview.questions[-1].answered is True


def test_continue_application_with_profile_refuses_when_resume_availability_is_not_immediate(monkeypatch):
    from jarvis.resume import store as resume_store
    from jarvis.resume.schema import Availability, Bilingual, JobPreferences, PersonalInfo, Resume

    resume = Resume(
        personal_info=PersonalInfo(full_name="Nicholas Birochi"),
        summary=Bilingual(pt="Resumo."),
        job_preferences=JobPreferences(availability=Availability(status="unspecified")),
    )
    monkeypatch.setattr(resume_store, "load", lambda: resume)

    _patch_profile(monkeypatch)
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Disponibilidade para início imediato?\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Disponibilidade para início imediato?"],
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert preview.can_submit is False
    assert page.filled == {}


def test_continue_application_with_profile_fills_nome_completo_from_the_resume(monkeypatch):
    # 2026-08-21, real miss found live (Vivo): "nome completo, sem
    # abreviações" resolved from the résumé's own full_name, same
    # reasoning as "linkedin".
    from jarvis.resume import store as resume_store
    from jarvis.resume.schema import Bilingual, PersonalInfo, Resume

    resume = Resume(personal_info=PersonalInfo(full_name="Nicholas Birochi"), summary=Bilingual(pt="Resumo."))
    monkeypatch.setattr(resume_store, "load", lambda: resume)

    _patch_profile(monkeypatch)
    page = FakeApplicationPage(
        step_texts=[
            "Alguém te indicou?\nSim\nNão",
            "Perguntas criadas pela empresa\n1.Informe seu nome completo, sem abreviações:\nResponder agora",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True, "Responder agora": True},
        company_questions=["1.Informe seu nome completo, sem abreviações:"],
        fill_selectors={'[id="input-1.Informe seu nome completo, sem abreviações:"]'},
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert page.filled == {'[id="input-1.Informe seu nome completo, sem abreviações:"]': "Nicholas Birochi"}
    assert preview.questions[-1].answered is True


def test_continue_application_with_profile_answers_sim_and_fills_a_known_referral_contact(monkeypatch):
    # Real, live-confirmed 2026-08-19 (see gupy.py's module docstring): when
    # the job's own company matches a known referral contact
    # (jarvis.sites.application_profile.load_referral_contacts()), the
    # FIRST Sim/Não pair is answered "Sim" and the two real, stable-ID
    # contact fields are filled -- the actual name/email must land in the
    # page fill (the real automation write) but never leak onto the
    # returned ApplicationQuestion or summary_text.
    _patch_profile(monkeypatch)
    contact = {"name": "Ana Beatriz Ferreira", "email": "ana.ferreira@itau-unibanco.com.br"}
    monkeypatch.setattr(application_profile, "load_referral_contacts", lambda: {"itau": contact})

    page = FakeApplicationPage(
        step_texts=[
            "Você está se candidatando para a vaga Trainee Itaú Unibanco 2027 na empresa Itaú Unibanco.",
            "Alguém te indicou?\nSim\nNão\nVocê trabalha na empresa?\nSim\nNão",
            "Tudo certo, revise sua candidatura.",
        ],
        referral_answer_count=2,
        click_results={"Continuar": True, "Salvar e continuar": True},
        fill_selectors={
            "#guiddedApplicationAdditionalDataIndicatedByNameInput",
            "#guiddedApplicationAdditionalDataIndicatedByEmailInput",
        },
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert page.last_is_referred is True
    assert page.filled == {
        "#guiddedApplicationAdditionalDataIndicatedByNameInput": contact["name"],
        "#guiddedApplicationAdditionalDataIndicatedByEmailInput": contact["email"],
    }
    assert preview.questions[0].answer == "Sim (contato conhecido preenchido)"
    # The real name/email must never leak onto the question object or the
    # human-facing summary -- same discipline as every other identity
    # field in this project, extended here to a THIRD PARTY's PII.
    assert contact["name"] not in str(preview.questions[0])
    assert contact["email"] not in str(preview.questions[0])
    assert contact["name"] not in (preview.summary_text or "")
    assert contact["email"] not in (preview.summary_text or "")
    assert "Continuar" in page.clicked
    assert "Salvar e continuar" in page.clicked


def test_continue_application_with_profile_reports_when_contact_fields_cannot_be_filled(monkeypatch):
    # If the real, stable-ID contact fields aren't found (page changed
    # since the last live check), the question is still recorded as
    # answered "Sim" (the label click itself is separate from the fill)
    # but flagged distinctly -- and still no PII leak.
    _patch_profile(monkeypatch)
    contact = {"name": "Rafael Tavares Lima", "email": "rafael.tavares@xpi.com.br"}
    monkeypatch.setattr(application_profile, "load_referral_contacts", lambda: {"xp": contact})

    page = FakeApplicationPage(
        step_texts=[
            "Você está se candidatando para a vaga Analista na empresa XP Investimentos.",
            "Alguém te indicou?\nSim\nNão",
            "Tudo certo, revise sua candidatura.",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True},
        fill_selectors=set(),  # every fill() call fails -- selectors not found
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert page.last_is_referred is True
    assert preview.questions[0].answer == "Sim (não consegui preencher o contato)"
    assert contact["name"] not in (preview.summary_text or "")
    assert contact["email"] not in (preview.summary_text or "")


def test_continue_application_with_profile_answers_nao_when_company_has_no_known_contact(monkeypatch):
    # Regression: a company that ISN'T one of the three named contacts
    # must keep the original, always-"Não" behavior.
    _patch_profile(monkeypatch)
    monkeypatch.setattr(
        application_profile,
        "load_referral_contacts",
        lambda: {"itau": {"name": "Ana Beatriz Ferreira", "email": "ana.ferreira@itau-unibanco.com.br"}},
    )

    page = FakeApplicationPage(
        step_texts=[
            "Você está se candidatando para a vaga Analista na empresa Nubank.",
            "Alguém te indicou?\nSim\nNão",
            "Tudo certo, revise sua candidatura.",
        ],
        referral_answer_count=1,
        click_results={"Continuar": True, "Salvar e continuar": True},
    )
    _patch_open_context(monkeypatch, page)

    preview = GupyAdapter().continue_application_with_profile("https://empresa.gupy.io/job/xyz", confirmed=True)

    assert page.last_is_referred is False
    assert preview.questions[0].answer == "Não (para todas)"


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
