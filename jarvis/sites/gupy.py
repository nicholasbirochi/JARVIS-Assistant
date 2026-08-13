"""First real SiteAdapter implementation -- see jarvis/sites/base.py for why
Gupy was picked first (not LinkedIn) and the hard rules every adapter here
follows (manual login only, apply_changes refuses without confirmed=True,
dry-run always comes first).

Verified against the real, live site (not guessed), via an actual logged-in
session:
- Domains/URLs: login.gupy.io/candidates/signin (login), portal.gupy.io
  (public landing + "Meu currículo" experience/skills/diversity form),
  login.gupy.io/candidates/profile (the *contact-info* edit form --
  name/email/phone/CPF/birth date. Confusingly hosted under the "login"
  subdomain, not "portal" -- found by clicking the account menu's "Editar
  perfil" link from a real session, not guessed).
- check_session()'s real signal: portal.gupy.io never redirects an
  anonymous visitor to the login page (it's a public page) -- the actual
  tell is whether its "Entrar" link (pointing at the login URL) is still
  present.
- _scrape_profile_fields()'s selectors (#name, #lastName,
  #input-with-button-email-input, #input-phone-mobileNumber): read directly
  off the live, authenticated profile page's DOM.

Gupy stores first/last name separately (no single "full name" field) and
the phone field holds the local number only (country code is a separate
selector next to it, defaulted to Brazil) -- _map_resume_to_gupy_fields()
and _scrape_profile_fields() both normalize around that so the diff in
build_update_plan() compares like with like instead of flagging a
formatting difference as a real change.

Real submission (apply_changes) verified live, human-supervised, 2026-08-06:
- Save button: `[data-testid="button-save"]`, never disabled by a dirty
  check -- safe to click even for a no-op resubmission.
- Clicking it fires (in order) a `POST .../validate-mobile-number` (only
  when the phone field was touched) and then
  `PATCH .../user-management/candidate/profile` (200) -- the real write --
  plus a `PATCH .../curriculum-management/candidate/curriculum/status`
  side effect. No navigation away from the page. Confirmed via a real,
  visible-browser no-op resubmission of the already-correct phone number:
  toast read "Dados salvos com sucesso!", value unchanged after reload.
- Only `full_name` and `phone` are wired to real writes (_WRITABLE_FIELDS).
  `email` is deliberately excluded -- it's also the login identifier, an
  actual value change there could trigger its own verification flow that
  has never been observed, so it stays untested and apply_changes() raises
  NotImplementedError if a plan ever contains an email change, rather than
  silently attempting it.

Job search (search_jobs(), added 2026-08-11): portal.gupy.io/job-search
is a real, unified marketplace search across every company using Gupy as
their ATS -- NOT per-company only, resolving earlier uncertainty about
this. URL: https://portal.gupy.io/job-search/term=<query> (found by
watching where the homepage's own search box navigates to, same method
as the other adapters). No login required. Listing cards are
`a[href*="/job/"]` -- each links out to the HIRING COMPANY's own
<company>.gupy.io subdomain, not portal.gupy.io, and encodes the job id
as base64 JSON (`{"jobId": ..., "source": "gupy_portal"}`) rather than a
plain path segment, so external_id is decoded from that instead of
parsed from the URL path like every other adapter here. Real selectors:
`h3` (title), the card's first `p` (company), and
`span[data-testid="job-location"]` (location) -- all clean, structured
markup, no truncated snippets or broken company names like InfoJobs.

Job APPLICATION flow (preview_application(), added 2026-08-12): a real,
live, human-supervised pilot against a genuine listing (Itaú Unibanco,
"Tech Lead | Engenharia de Software", job id 11666964), reachable via a
company-specific subdomain (vemproitau.gupy.io) rather than portal.gupy.io
-- confirmed live that the portal.gupy.io session cookies DO carry over
there (the nav shows "Editar perfil"/"Sair", i.e. still logged in as the
candidate). Real, confirmed findings:
- Apply link: `[data-testid="apply-link"]` on the job page, href
  `/candidates/jobs/<id>/apply?jobBoardSource=gupy_portal` (site-relative
  -- resolve with urljoin against the current page URL).
- The apply flow is NOT one-click. Real sequence observed: (1) an initial
  "vamos continuar sua candidatura?" gate, single "Continuar" button --
  merely opening this URL creates a real numbered application id
  (`/candidates/applications/<id>/steps/<id>/curriculum`) but revisiting
  the job listing page afterward still shows a plain "Candidatar-se"
  button (not "continuar"/"já se candidatou"), so this gate alone does
  NOT appear to register as a real application from the listing's own
  point of view; (2) Gupy's own STANDARD platform questions ("Alguém
  te indicou?" / "Você trabalha na empresa?", both yes/no) plus an
  optional free-text "onde encontrou a vaga" field, then "Salvar e
  continuar"; (3) any company-specific "Perguntas criadas pela empresa"
  step, revealed only after clicking "Responder agora" -- for the real
  Itaú listing tested, this asked for the candidate's **RG** and
  **current salary**, with an on-page warning that answers "não poderão
  ser editadas depois". See base.py's question_requires_stop() and the
  hard rule above SiteAdapter: JARVIS never fabricates an answer here,
  and never auto-answers ANY company-specific question even if it looks
  simple -- only Gupy's own two standard referral questions are
  auto-answered (both always "Não" -- factually true for any external
  candidate applying cold).
- Company questions are extracted INDIVIDUALLY (2026-08-13, real DOM
  confirmed live): each is its own `<h3>` whose text starts with "N."
  (e.g. `<h3 class="sc-bklklh aRUgP">1.Qual sua pretensão salarial
  atual?</h3>` -- the class is build-hashed and unstable, so matching is
  on the numbered-prefix text pattern instead). Each question is
  individually classified via base.py's is_hard_pii_question() (RG/CPF/
  birth date -- never even received from Nicholas) vs the broader
  question_requires_stop() (also covers salary/marital status -- still a
  stop today, but reported with a different, more precise reason).
  Confirmed live against BOTH real listings tested: Itaú's RG question
  correctly flags is_hard_pii=True; BIP Brasil's "pretensão salarial"
  question correctly flags is_hard_pii=False while still blocking.
- DOM quirk: the "Sim"/"Não" choices for both the standard referral
  questions and (presumably) company yes/no questions are `<span>` text
  nodes inside `<label>` elements -- there is NO native, visible
  `<input type="radio">` findable via `document.querySelectorAll('input')`
  (confirmed live: that query returned zero results on this exact step).
  Click the `<label>` itself, found by an exact direct-text-content match
  on its child `<span>` (not a CSS class -- Gupy's classes here are
  build-hashed, e.g. `sc-bKNmIE eNMMGn`, and not stable across deploys).
- Real anti-automation signal observed: Gupy's own bundled Hotjar script
  logged "Hotjar not launching due to suspicious userAgent" when run
  headless (a real HeadlessChrome user agent) -- doesn't block the flow,
  but is a genuine, confirmed detection signal worth knowing about before
  running this at any real volume.
- **NOT YET VERIFIED**: what the real final review/submit screen looks
  like, or its button's exact text/selector -- every real listing tested
  so far hit a company-specific question first and stopped there before
  reaching it. preview_application() therefore NEVER returns
  can_submit=True yet, and there is no apply_to_job() in this file --
  writing one now would mean guessing the final click, which this
  project's whole methodology (live-verify, never guess) exists to
  avoid.
- **Real finding, 2026-08-13, that changes the outlook here**: a SECOND
  real, different, live-tested listing (BIP Brasil, unrelated to Itaú)
  ALSO hit a company-specific question step -- this one asked "Qual sua
  pretensão salarial atual?" (current salary expectation) plus two
  company-culture questions. Two for two real companies tested both
  blocked on a financial/custom question before ever reaching a final
  submit screen. This is a real signal, not a coincidence: Gupy-hosted
  employers commonly attach at least one custom screening question
  (often salary), which means the "completes fully automatically" path
  may be rare or nonexistent in practice, not just untested. Worth
  knowing before investing more effort chasing a fully-automated
  end-to-end submission here -- the honest, buildable ceiling right now
  is preview_application()'s safety check, not a true one-click apply.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

from jarvis.resume.schema import Resume
from jarvis.sites import session
from jarvis.sites.base import (
    ApplicationPreview,
    ApplicationQuestion,
    ChangePreview,
    JobListing,
    PlannedFieldChange,
    SessionStatus,
    SiteAdapter,
    SiteProfileSnapshot,
    UpdatePlan,
    UpdateResult,
    is_hard_pii_question,
    question_requires_stop,
)

SITE_NAME = "gupy"

# Only these site_field values have a real, live-verified write path (see
# module docstring). Anything else in a plan makes apply_changes() refuse
# the whole plan rather than silently writing part of it.
_WRITABLE_FIELDS = {"full_name", "phone"}


def _strip_country_code(phone: str | None) -> str | None:
    """Résumé phone numbers are stored as "+55 (11) 95827-5250"; Gupy's
    mobile-number field holds just "(11) 95827-5250" (country code is a
    separate selector, defaulted to Brazil). Strip the prefix so the two
    are compared on equal footing instead of always looking different."""
    if phone is None:
        return None
    return phone.removeprefix("+55").strip()


def _split_full_name(full_name: str) -> tuple[str, str]:
    """Gupy stores first/last name as two separate fields; the résumé keeps
    one combined string. Splits on the first space -- verified live against
    the real account ("Nicholas Birochi" -> #name="Nicholas",
    #lastName="Birochi"). A name with no space becomes an empty last name
    rather than raising; still a defensible mapping, not a crash."""
    first, _, rest = full_name.partition(" ")
    return first, rest


def _map_resume_to_gupy_fields(resume: Resume) -> dict[str, Any]:
    """Canonical résumé -> Gupy's own field names. Only the contact-info
    fields verified on the real "Editar perfil" page are mapped --
    experience/education/certifications live in a separate, structured
    sub-form ("Meu currículo") not yet inspected; left out rather than
    guessed."""
    return {
        "full_name": resume.personal_info.full_name,
        "phone": _strip_country_code(resume.personal_info.phone),
        "email": resume.personal_info.email,
    }


def _is_authenticated(context) -> bool:
    """Shared by check_session() and login()'s post-login verification --
    portal.gupy.io itself is a public page and does NOT force-redirect an
    anonymous visitor to the login page (verified live), so a URL-only
    check silently reports "logged in" even for a session with no real
    auth cookie in it (caught live -- see gupy.py's module docstring). The
    real signal is whether the "Entrar" link (pointing at the login page)
    is still present."""
    from jarvis.config import GUPY_LOGIN_URL, GUPY_PORTAL_URL

    page = context.new_page()
    try:
        page.goto(GUPY_PORTAL_URL)
        page.wait_for_load_state("networkidle")
        if "login.gupy.io" in page.url:
            return False
        login_link = page.query_selector(f'a[href="{GUPY_LOGIN_URL}"]')
        return login_link is None
    finally:
        page.close()


class GupyAdapter(SiteAdapter):
    site_name = SITE_NAME

    def check_session(self) -> SessionStatus:
        if not session.has_saved_session(self.site_name):
            return SessionStatus.NOT_LOGGED_IN

        from jarvis.config import SITES_HEADLESS

        p, context = session.open_context(self.site_name, headless=SITES_HEADLESS)
        try:
            return SessionStatus.AUTHENTICATED if _is_authenticated(context) else SessionStatus.SESSION_EXPIRED
        except Exception:
            return SessionStatus.UNKNOWN_ERROR
        finally:
            context.close()
            p.stop()

    def login(self) -> bool:
        """Not part of the SiteAdapter interface (check_session() never logs
        in itself, by design) -- this is the explicit, separate, one-time
        manual step the CLI's `gupy-login` command calls. Returns whether
        the session actually verified as authenticated afterward."""
        from jarvis.config import GUPY_LOGIN_URL

        return session.login_interactively(self.site_name, GUPY_LOGIN_URL, verify_fn=_is_authenticated)

    def inspect_current_profile(self) -> SiteProfileSnapshot:
        from jarvis.config import GUPY_PROFILE_URL, SITES_HEADLESS

        p, context = session.open_context(self.site_name, headless=SITES_HEADLESS)
        try:
            page = context.new_page()
            page.goto(GUPY_PROFILE_URL)
            page.wait_for_load_state("networkidle")
            fields = self._scrape_profile_fields(page)
        finally:
            context.close()
            p.stop()
        return SiteProfileSnapshot(
            site_name=self.site_name,
            fields=fields,
            captured_at=datetime.now(timezone.utc).isoformat(),
        )

    def _scrape_profile_fields(self, page) -> dict[str, Any]:
        first_name = page.input_value("#name")
        last_name = page.input_value("#lastName")
        return {
            "full_name": f"{first_name} {last_name}".strip(),
            "email": page.input_value("#input-with-button-email-input"),
            "phone": page.input_value("#input-phone-mobileNumber"),
        }

    def build_update_plan(self, resume: Resume, current: SiteProfileSnapshot) -> UpdatePlan:
        desired = _map_resume_to_gupy_fields(resume)
        resume_field_paths = {
            "full_name": "personal_info.full_name",
            "phone": "personal_info.phone",
            "email": "personal_info.email",
        }
        changes = [
            PlannedFieldChange(
                site_field=field_name,
                current_value=current.fields.get(field_name),
                new_value=new_value,
                resume_field_path=resume_field_paths[field_name],
            )
            for field_name, new_value in desired.items()
            if new_value is not None and current.fields.get(field_name) != new_value
        ]
        return UpdatePlan(site_name=self.site_name, changes=changes)

    def preview_changes(self, plan: UpdatePlan) -> ChangePreview:
        if not plan.changes:
            summary = "Nenhuma mudança -- o perfil na Gupy já bate com o currículo local."
        else:
            lines = [
                f"- {c.site_field}: {c.current_value!r} -> {c.new_value!r} "
                f"(origem: {c.resume_field_path})"
                for c in plan.changes
            ]
            summary = f"{len(plan.changes)} mudança(s) propostas para {plan.site_name}:\n" + "\n".join(
                lines
            )
        return ChangePreview(site_name=self.site_name, plan=plan, summary_text=summary)

    def apply_changes(self, plan: UpdatePlan, confirmed: bool) -> UpdateResult:
        if not confirmed:
            return UpdateResult(
                site_name=self.site_name,
                applied=False,
                error="Recusado: apply_changes exige confirmed=True, só depois de "
                "preview_changes() ter sido mostrado a um humano.",
            )
        if not plan.changes:
            return UpdateResult(site_name=self.site_name, applied=True, changes_applied=[])

        unsupported = [c.site_field for c in plan.changes if c.site_field not in _WRITABLE_FIELDS]
        if unsupported:
            raise NotImplementedError(
                f"Envio real ainda não coberto para: {', '.join(unsupported)}. Nome e "
                "telefone já foram testados ao vivo (ver o docstring de gupy.py); email "
                "é também o identificador de login e pode disparar um fluxo de "
                "verificação separado nunca observado -- precisa do próprio teste "
                "supervisionado antes de confiar nele."
            )

        from jarvis.config import GUPY_PROFILE_URL, SITES_HEADLESS

        p, context = session.open_context(self.site_name, headless=SITES_HEADLESS)
        try:
            page = context.new_page()
            page.goto(GUPY_PROFILE_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_load_state("networkidle", timeout=60_000)

            for change in plan.changes:
                self._fill_field(page, change.site_field, change.new_value)

            save_btn = page.query_selector('[data-testid="button-save"]')
            if save_btn is None:
                return UpdateResult(
                    site_name=self.site_name,
                    applied=False,
                    error="Botão Salvar não encontrado -- a página pode ter mudado desde "
                    "a última verificação ao vivo.",
                )
            save_btn.click()
            page.wait_for_load_state("networkidle", timeout=60_000)

            evidence_path = self._record_evidence(plan)

            fields_after = self._scrape_profile_fields(page)
            failed = [c for c in plan.changes if fields_after.get(c.site_field) != c.new_value]
            if failed:
                return UpdateResult(
                    site_name=self.site_name,
                    applied=False,
                    error="Clicou Salvar, mas o perfil não reflete a mudança em: "
                    f"{', '.join(c.site_field for c in failed)} -- confira manualmente.",
                    evidence_path=evidence_path,
                )
            return UpdateResult(
                site_name=self.site_name,
                applied=True,
                changes_applied=plan.changes,
                evidence_path=evidence_path,
            )
        finally:
            context.close()
            p.stop()

    def _fill_field(self, page, site_field: str, value: Any) -> None:
        if site_field == "full_name":
            first, last = _split_full_name(value)
            page.fill("#name", first)
            page.fill("#lastName", last)
        elif site_field == "phone":
            page.fill("#input-phone-mobileNumber", value)
            page.locator("#input-phone-mobileNumber").blur()
            # Gupy fires its own async POST .../validate-mobile-number on
            # blur (observed live) -- wait for the network to settle so
            # Save isn't clicked mid-validation.
            page.wait_for_load_state("networkidle", timeout=10_000)
        else:  # pragma: no cover -- unreachable, apply_changes filters first
            raise NotImplementedError(f"Campo não suportado para escrita: {site_field!r}")

    def _record_evidence(self, plan: UpdatePlan) -> str | None:
        """Audit-trail record for a real submission -- deliberately a small
        JSON record of what changed (field/old/new/when), NOT a screenshot.
        The profile page also displays CPF and birth date right next to the
        fields we actually write; a full-page screenshot would capture those
        incidentally even though the write itself never touches them.
        Best-effort -- a failed write here shouldn't fail the whole apply,
        the actual site write already happened by this point."""
        import json

        from jarvis.config import SITES_EVIDENCE_DIR

        try:
            SITES_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = SITES_EVIDENCE_DIR / f"{self.site_name}_{stamp}.json"
            record = {
                "site_name": self.site_name,
                "applied_at": datetime.now(timezone.utc).isoformat(),
                "changes": [
                    {
                        "field": c.site_field,
                        "old_value": c.current_value,
                        "new_value": c.new_value,
                        "resume_field_path": c.resume_field_path,
                    }
                    for c in plan.changes
                ],
            }
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            return str(path)
        except Exception:
            return None

    def search_jobs(self, query: str, *, max_results: int = 60) -> list[JobListing]:
        """Read-only, no login required (see module docstring) -- callers
        should run the result through jarvis.sites.job_matching before
        treating it as "matches" (~12 items per page).

        Pagination: real, confirmed live -- page 1 is the bare
        job-search/term=<query> URL, page N>=2 appends ?page=N (found by
        clicking the results page's own numbered pagination buttons and
        reading the resulting URL). Stops once a page returns no new
        cards (real end of results) or max_results is reached, whichever
        comes first."""
        import urllib.parse

        from jarvis.config import SITES_HEADLESS

        base_url = f"https://portal.gupy.io/job-search/term={urllib.parse.quote(query)}"

        p, context = session.open_context(self.site_name, headless=SITES_HEADLESS)
        try:
            page = context.new_page()
            cards: list[dict] = []
            page_num = 1
            while len(cards) < max_results:
                url = base_url if page_num == 1 else f"{base_url}?page={page_num}"
                page.goto(url, timeout=45_000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                page_cards = self._extract_listing_cards(page)
                if not page_cards:
                    break
                cards.extend(page_cards)
                page_num += 1
                if page_num > 6:  # safety bound -- don't page forever
                    break
        finally:
            context.close()
            p.stop()

        listings = []
        for card in cards:
            listing = _card_to_job_listing(card)
            if listing is not None:
                listings.append(listing)
        return listings

    def _extract_listing_cards(self, page) -> list[dict]:
        """Raw card data, straight off the DOM -- kept as a thin, separate
        method so _card_to_job_listing()'s conversion/validation logic
        (below) can be unit-tested without a real page.evaluate() call."""
        return page.evaluate(
            """
            () => Array.from(document.querySelectorAll("a[href*='/job/']")).map(a => {
                const title = a.querySelector('h3');
                const company = a.querySelector('p');
                const location = a.querySelector('[data-testid="job-location"]');
                return {
                    href: a.getAttribute('href'),
                    title: title ? title.textContent.trim() : null,
                    company: company ? company.textContent.trim() : null,
                    location: location ? location.textContent.trim() : null,
                };
            })
            """
        )

    def preview_application(self, job_url: str) -> ApplicationPreview:
        """Dry-run: walks as far into a real job's application flow as
        it's SAFE to go automatically (the initial gate + Gupy's own two
        standard referral questions, always answered "Não"/"Não" -- see
        module docstring), then stops the instant it reaches ANY
        company-specific question. Never submits anything, and
        can_submit is always False today -- the real final submit screen
        has never been observed live (see module docstring). This is the
        apply-flow equivalent of preview_changes() above."""
        from jarvis.config import SITES_HEADLESS

        p, context = session.open_context(self.site_name, headless=SITES_HEADLESS)
        try:
            page = context.new_page()
            page.goto(job_url, timeout=45_000, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=30_000)
            page.wait_for_timeout(2000)

            apply_href = self._get_apply_href(page)
            if apply_href is None:
                reason = (
                    'Não encontrei o link "Candidatar-se" nessa página -- a vaga pode ter '
                    "sido removida ou a estrutura da página mudou desde a última verificação."
                )
                return ApplicationPreview(
                    site_name=self.site_name, job_url=job_url, can_submit=False, blocked_reason=reason
                )

            page.goto(urljoin(page.url, apply_href), timeout=45_000, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=30_000)
            page.wait_for_timeout(2000)

            questions: list[ApplicationQuestion] = []

            self._click_text_button(page, "Continuar")
            page.wait_for_timeout(1500)
            page.wait_for_load_state("networkidle", timeout=30_000)

            referral_text = self._extract_step_text(page)
            answered_count = self._answer_referral_labels(page)
            if answered_count:
                questions.append(
                    ApplicationQuestion(text=referral_text, answered=True, answer="Não (para todas)")
                )
                page.wait_for_timeout(1000)
                self._click_text_button(page, "Salvar e continuar")
                page.wait_for_timeout(2000)
                page.wait_for_load_state("networkidle", timeout=30_000)

            step_text = self._extract_step_text(page)
            if "Perguntas criadas pela empresa" in step_text or "Responder agora" in step_text:
                self._click_text_button(page, "Responder agora")
                page.wait_for_timeout(1500)
                company_questions = self._extract_company_questions(page)
                if not company_questions:
                    # Real selector (h3 whose text starts with "N.") found
                    # nothing -- fall back to the whole block so nothing
                    # is silently lost, same as before this change.
                    company_questions = [self._extract_step_text(page)]
                for q_text in company_questions:
                    questions.append(
                        ApplicationQuestion(text=q_text, answered=False, is_hard_pii=is_hard_pii_question(q_text))
                    )

                pii_questions = [q for q in questions if q.is_hard_pii]
                other_blocking = [q for q in questions if not q.is_hard_pii and question_requires_stop(q.text)]
                if pii_questions:
                    reason = (
                        "Essa vaga pede documento oficial (RG/CPF) ou data de nascimento numa "
                        "pergunta própria da empresa -- o JARVIS nunca recebe nem repassa esse "
                        "dado, mesmo que você queira ditar a resposta."
                    )
                elif other_blocking:
                    reason = (
                        "Essa vaga tem pergunta(s) própria(s) sobre dado sensível (salário, "
                        "estado civil) -- o JARVIS ainda não responde isso sozinho."
                    )
                else:
                    reason = (
                        "Essa vaga tem pergunta(s) própria(s) da empresa -- o JARVIS não "
                        "responde nenhuma pergunta específica de empresa sozinho, mesmo que "
                        "pareça simples."
                    )
                return ApplicationPreview(
                    site_name=self.site_name,
                    job_url=job_url,
                    can_submit=False,
                    blocked_reason=reason,
                    questions=questions,
                    summary_text=self._render_application_summary(reason, questions),
                )

            reason = (
                "Nenhuma pergunta própria da empresa apareceu nessa vaga, mas o clique final "
                "de envio nunca foi verificado ao vivo em nenhuma candidatura real ainda -- "
                "por segurança o JARVIS para aqui em vez de inventar qual botão clicar."
            )
            return ApplicationPreview(
                site_name=self.site_name,
                job_url=job_url,
                can_submit=False,
                blocked_reason=reason,
                questions=questions,
                summary_text=self._render_application_summary(reason, questions),
            )
        finally:
            context.close()
            p.stop()

    def _get_apply_href(self, page) -> str | None:
        return page.evaluate(
            """
            () => {
                const el = document.querySelector('[data-testid="apply-link"]');
                return el ? el.getAttribute('href') : null;
            }
            """
        )

    def _click_text_button(self, page, text: str) -> bool:
        return page.evaluate(
            f"""
            () => {{
                const el = Array.from(document.querySelectorAll('button, a'))
                    .find(b => b.textContent.trim() === {text!r});
                if (el) {{ el.click(); return true; }}
                return false;
            }}
            """
        )

    def _answer_referral_labels(self, page) -> int:
        """Clicks every <label> wrapping a "Não" <span> -- see module
        docstring's DOM-quirk note (no plain <input type="radio"> exists
        to target instead)."""
        return page.evaluate(
            """
            () => {
                let count = 0;
                document.querySelectorAll('label').forEach(label => {
                    const span = Array.from(label.querySelectorAll('span'))
                        .find(s => s.textContent.trim() === 'Não');
                    if (span) { label.click(); count++; }
                });
                return count;
            }
            """
        )

    def _extract_step_text(self, page) -> str:
        return page.evaluate("() => (document.querySelector('main') || document.body).innerText.trim()")

    def _extract_company_questions(self, page) -> list[str]:
        """Individual company-specific questions, one per real <h3>
        element whose text starts with "N." -- confirmed live 2026-08-13
        against a real listing (BIP Brasil): each question is its own
        <h3 class="sc-bklklh aRUgP">1.Question text</h3>. The class name
        is build-hashed and NOT stable across Gupy deploys (same caveat
        as the "Não" radio labels elsewhere in this file), so matching is
        done on the numbered-prefix TEXT PATTERN instead, which is far
        more likely to survive a redeploy."""
        return page.evaluate(
            """
            () => Array.from(document.querySelectorAll('main h3, body h3'))
                .map(h => h.textContent.trim())
                .filter(t => /^\\d+\\./.test(t))
            """
        )

    def _render_application_summary(self, reason: str, questions: list[ApplicationQuestion]) -> str:
        lines = [f"Candidatura em {self.site_name}: BLOQUEADA -- {reason}"]
        for q in questions:
            if q.answered:
                status = f"respondida automaticamente ({q.answer})"
            elif q.is_hard_pii:
                status = "NÃO respondida -- documento oficial, o JARVIS nunca pede isso"
            else:
                status = "NÃO respondida -- precisa de você"
            lines.append(f"- {status}: {q.text[:200]}")
        return "\n".join(lines)


def _decode_job_id(href: str) -> str | None:
    """Gupy encodes the job id as base64 JSON in the URL's path segment
    (e.g. `.../job/eyJqb2JJZCI6MTIwNDc4ODQs...` decodes to
    `{"jobId": 12047884, "source": "gupy_portal"}`) rather than a plain
    numeric path segment like every other adapter here -- confirmed live
    by decoding a real URL. Returns None on any malformed input rather
    than raising, since this is scraped, not trusted, data."""
    import base64
    import binascii
    import json

    try:
        encoded = href.rstrip("/").split("/job/")[-1].split("?")[0]
        # base64.b64decode needs correct padding; Gupy's URLs sometimes
        # omit the trailing "=" that plain b64decode requires.
        padded = encoded + "=" * (-len(encoded) % 4)
        decoded = json.loads(base64.b64decode(padded))
        job_id = decoded.get("jobId")
        return str(job_id) if job_id is not None else None
    except (ValueError, KeyError, binascii.Error, UnicodeDecodeError):
        return None


def _card_to_job_listing(card: dict) -> JobListing | None:
    if not card.get("title") or not card.get("href"):
        return None
    external_id = _decode_job_id(card["href"])
    if external_id is None:
        return None
    return JobListing(
        site_name=SITE_NAME,
        external_id=external_id,
        title=card["title"],
        company=card.get("company"),
        location=card.get("location"),
        url=card["href"],
    )
