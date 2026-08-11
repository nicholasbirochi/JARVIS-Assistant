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
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from jarvis.resume.schema import Resume
from jarvis.sites import session
from jarvis.sites.base import (
    ChangePreview,
    JobListing,
    PlannedFieldChange,
    SessionStatus,
    SiteAdapter,
    SiteProfileSnapshot,
    UpdatePlan,
    UpdateResult,
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

    def search_jobs(self, query: str) -> list[JobListing]:
        """Read-only, no login required (see module docstring) -- callers
        should run the result through jarvis.sites.job_matching before
        treating it as "matches". Only the first results page (~12 items)
        is fetched -- pagination is out of scope for this round."""
        import urllib.parse

        from jarvis.config import SITES_HEADLESS

        url = f"https://portal.gupy.io/job-search/term={urllib.parse.quote(query)}"

        p, context = session.open_context(self.site_name, headless=SITES_HEADLESS)
        try:
            page = context.new_page()
            page.goto(url, timeout=45_000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            cards = self._extract_listing_cards(page)
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
