"""Local-only HTTP server for the job-application portal -- serves a
real, interactive page at `/` whose buttons genuinely run on this Mac
(unlike the earlier Claude Artifact version, which is hosted on
Anthropic's own servers with no path back to local Playwright/JARVIS at
all -- see this module's origin: Nicholas asked to "mude para local...
a gente conseguir fazer as inscrições", after already being told the
Artifact structurally can't do this).

Same pattern as visualizer/server.py: plain stdlib http.server,
bound to 127.0.0.1 only, ThreadingHTTPServer so a slow request (real
Playwright automation, 10-30+ seconds) doesn't block other connections.
Different port (8767, not the visualizer's 8765 or the xtts worker's
8766) so all three can run at once.

Routes:
- GET  /            -- the page, rendered fresh from the in-memory
  tiered report (see refresh_data()). Empty state if nothing has been
  fetched yet in this process.
- POST /api/check   -- {"url": "..."} -> jarvis.assistant.tools.
  check_job_application(url) -- read-only, never submits anything.
- POST /api/apply   -- {"url": "..."} -> assistant.tools.
  continue_job_application(url, finalize=True) -- a REAL, mutating,
  FINAL action: fills the live form using the local application
  profile (same all-or-nothing rule as everywhere else -- one missing
  field blocks the whole step) and, if that succeeds, clicks the real
  final submit button too (2026-08-25, changed at Nicholas's explicit
  request -- previously stopped right after filling). The browser's
  own confirm() dialog (in page_template.html) -- which spells out that
  this sends the application for real -- is the human-in-the-loop check
  before this ever fires, not a second code-level gate.
- POST /api/refresh -- reruns a real, fresh multi-site search
  (blocking -- the client's fetch() just waits, showing a loading
  state; no fake progress bar, no background job queue for this first
  version).

Why AmazonJobsAdapter is included here but NOT in jarvis.job_search's
own _default_adapters(): that decision (kept conservative pending more
real-world runs, see amazon_jobs.py's docstring) is about the
voice/text-triggered find_matching_jobs() tool specifically, which can
fire unattended and often. This portal is an explicit, manually-opened
action -- a reasonable place to include the one adapter that's
actually proven to add real bank/bigtech coverage (see this module's
2026-08 development history)."""

from __future__ import annotations

import html
import json
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sites.base import JobListing

_PORTAL_DIR = Path(__file__).resolve().parent
_TEMPLATE_PATH = _PORTAL_DIR / "page_template.html"
_ANALYSIS_TEMPLATE_PATH = _PORTAL_DIR / "analysis_template.html"
_FAVICON_LINK_PATH = _PORTAL_DIR / "favicon_link.html"
_CSS_PATH = _PORTAL_DIR / "portal.css"
_JS_PATH = _PORTAL_DIR / "portal.js"

_TIER_META = {
    # 2026-09-05, "quero candidaturas focadas nesse tipo de vagas
    # também! internacionais remotas!!!!" -- listed first, ahead of
    # "banco", as the explicit new focus. Cross-cutting (see
    # group_by_tier()'s docstring): the same listing can also appear in
    # its normal company tier below, so its count is deliberately
    # excluded from the "vagas no total" stat (see render_page()) to
    # avoid double-counting.
    "internacional": {
        "label": "Remoto/Internacional",
        "emoji": "🌎",
        "sub": "Vagas 100% remotas -- empresa estrangeira aberta a candidatos no Brasil, remoto nacional comum, ou 'trabalhe de qualquer lugar' sem restrição de país (as 3 leituras que você validou)",
    },
    "banco": {"label": "Bancos", "emoji": "🏦", "sub": "Bancos tradicionais nomeados (Itaú, Bradesco, Santander, BTG e outros)"},
    "fintech": {"label": "Fintechs", "emoji": "💳", "sub": "Fintechs nomeadas (Nubank, C6 Bank, Stone, PicPay, Cora e outras)"},
    "bigtech": {"label": "Bigtechs", "emoji": "💻", "sub": "Bigtechs nomeadas (Google, Amazon, Mercado Livre, iFood e outras)"},
    "startup": {"label": "Startups", "emoji": "🚀", "sub": "Startups/scale-ups nomeadas (Gupy, Hotmart, QuintoAndar, BairesDev e outras)"},
    "outras": {"label": "Outras empresas", "emoji": "🏢", "sub": "Todas as outras vagas relevantes -- mesmas restrições, empresa não está nas listas nomeadas acima"},
}

_SITE_LABELS = {
    "infojobs": "InfoJobs",
    "catho": "Catho",
    "gupy": "Gupy",
    "amazon_jobs": "Amazon Jobs",
    "ifood_careers": "iFood",
    "btg_careers": "BTG Pactual",
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "remoteok": "RemoteOK",
    "weworkremotely": "We Work Remotely",
}

_server: ThreadingHTTPServer | None = None
_server_lock = threading.Lock()
_tiers: dict[str, list[JobListing]] | None = None
_tiers_lock = threading.Lock()


def _portal_adapters(*, include_linkedin: bool = False) -> dict[str, object]:
    """The eight base adapters always run, on every path (manual button
    click or refresh_if_due()'s unattended daily timer). LinkedIn
    (include_linkedin=True) is deliberately opt-in and NOT included by
    default -- see linkedin.py's module docstring: it's this project's
    highest-risk site, and while search_jobs() runs as an anonymous
    guest (no real risk to Nicholas's actual account), it's still kept
    out of the fully unattended daily refresh so it only ever runs when
    he's the one triggering it (the portal's "Atualizar vagas agora"
    button, or opening the portal for the first time).

    RemoteOK and We Work Remotely (sites/remoteok.py,
    sites/weworkremotely.py, both 2026-08-19) are in the base
    set, no opt-in needed -- unlike LinkedIn/Indeed they're real,
    public, documented feeds (JSON API / RSS) with no anti-bot layer and
    no login-adjacent risk to weigh, safe to run unattended the same as
    InfoJobs/Catho/Gupy.

    Indeed (sites/indeed.py) is deliberately NOT included here at
    all, opt-in or not -- confirmed live 2026-08-11 that a handful of
    search_jobs() calls in a short window (exactly this sweep's pattern:
    12+ terms back to back) triggers a real IP-level block from Indeed
    that also affects Nicholas's own normal browsing from this machine.
    That's not a "be extra careful" call, it's an already-observed
    failure mode this sweep would reliably reproduce."""
    from sites.amazon_jobs import AmazonJobsAdapter
    from sites.btg_careers import BTGCareersAdapter
    from sites.catho import CathoAdapter
    from sites.gupy import GupyAdapter
    from sites.ifood_careers import IFoodCareersAdapter
    from sites.infojobs import InfoJobsAdapter
    from sites.remoteok import RemoteOkAdapter
    from sites.weworkremotely import WeWorkRemotelyAdapter

    adapters: dict[str, object] = {
        "infojobs": InfoJobsAdapter(),
        "catho": CathoAdapter(),
        "gupy": GupyAdapter(),
        "amazon_jobs": AmazonJobsAdapter(),
        "ifood_careers": IFoodCareersAdapter(),
        "btg_careers": BTGCareersAdapter(),
        "remoteok": RemoteOkAdapter(),
        "weworkremotely": WeWorkRemotelyAdapter(),
    }
    if include_linkedin:
        from sites.linkedin import LinkedInAdapter

        adapters["linkedin"] = LinkedInAdapter()
    return adapters


def refresh_data(resume=None, *, adapters: dict[str, object] | None = None) -> dict[str, list[JobListing]]:
    """Runs a real, fresh search (jarvis.job_search.run_job_search) and
    tiers the combined local+remote relevant results via
    jarvis.sites.job_matching.group_by_tier(). Stores the result for
    subsequent page renders/route handlers. resume/adapters are
    injectable for tests; production calls load the real résumé, and
    default to _portal_adapters()'s base set (no LinkedIn) when adapters
    isn't given -- callers that want the extended set (LinkedIn
    included) pass adapters=_portal_adapters(include_linkedin=True)
    explicitly (see _handle_refresh() and tools.open_job_portal()).

    Deliberately does NOT use run_job_search()'s bounded defaults
    (_MAX_TERMS=3) -- real gap found live 2026-08-14: once Nicholas set
    7 explicit target_roles, the portal's own "Atualizar vagas agora"
    button (calling this with no args) only ever searched the first 3,
    undoing the deeper coverage a manually-run script had found minutes
    earlier. This is an explicit, manually-triggered, patient action
    (unlike find_matching_jobs()'s voice/text path, which stays bounded
    on purpose) -- max_terms=0 means "every term", max_results_per_term
    is raised accordingly.

    group_by_tier(..., include_other=True) -- 2026-08-17, real request
    ("quero pelo menos mais de 200 vagas"): the four named-company tiers
    alone are gated by real, current openings at ~100 curated companies
    and were never going to reach that on volume alone. A fifth "outras"
    bucket now holds every other relevant listing (still real, still
    matches every other restriction) instead of silently dropping it.

    group_by_tier(..., include_international=True) -- 2026-09-05, "quero
    candidaturas focadas nesse tipo de vagas também! internacionais
    remotas!!!!": adds a sixth, cross-cutting "internacional" bucket
    (full home-office listings, any company) -- see that function's own
    docstring for why it's not also gated on has_international_signal().

    max_results_per_term=100 -- 2026-08-19 ("cace cada vez mais!!!!!"):
    raised from 50 after noticing it was the ACTUAL bottleneck for
    several sites, not their own capacity -- Catho/Gupy/InfoJobs each
    default to max_results=60 and BTG/iFood to 100 when called directly,
    but every one of them was being handed 50 here regardless, below
    what they can genuinely page through. 100 lets each site reach its
    own real ceiling instead of an arbitrary lower one imposed here."""
    from job_search import run_job_search
    from sites.job_matching import group_by_tier

    if resume is None:
        from resume import store

        resume = store.load()
    if adapters is None:
        adapters = _portal_adapters()

    report = run_job_search(resume, adapters=adapters, max_terms=0, max_results_per_term=100)
    combined = report.local + report.remote
    tiers = group_by_tier(combined, include_other=True, include_international=True)

    with _tiers_lock:
        global _tiers
        _tiers = tiers
    return tiers


def _last_refresh_path() -> Path:
    from config import DATA_DIR

    return DATA_DIR / "job_matches" / "portal_last_refresh.json"


def _read_last_refresh() -> datetime | None:
    path = _last_refresh_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return datetime.fromisoformat(data["last_refresh"])
    except Exception:
        return None


def _write_last_refresh(when: datetime) -> None:
    path = _last_refresh_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_refresh": when.isoformat()}), encoding="utf-8")


def is_refresh_due(*, now: datetime | None = None) -> bool:
    """True if the deep portal sweep has never run, or the last real run
    was 24h+ ago -- own tracking file (portal_last_refresh.json), same
    pattern as job_search.py's is_daily_search_due() but kept
    separate: that one tracks the shallow, bounded voice/text report;
    this tracks the deep, unbounded portal sweep (max_terms=0,
    max_results_per_term=50, 5 adapters, include_other=True) -- they run
    on independent schedules, at Nicholas's explicit request
    (2026-08-17) to make "essa varredura" (the deep one specifically)
    daily, not the shallow one."""
    now = now or datetime.now(timezone.utc)
    last_refresh = _read_last_refresh()
    if last_refresh is None:
        return True
    return (now - last_refresh) >= timedelta(hours=24)


def refresh_if_due(resume=None, *, adapters: dict[str, object] | None = None, now: datetime | None = None) -> bool:
    """Runs refresh_data() (the real, deep sweep) only if is_refresh_due()
    -- returns whether a refresh actually happened, so a caller polling
    this often (e.g. hourly while JARVIS is running, see
    menubar.py) doesn't re-search needlessly. Updates the "last
    refresh" timestamp regardless of whether every site succeeded -- one
    site being temporarily down shouldn't make this retry every poll for
    the rest of the day, same reasoning as job_search.py's
    run_daily_search_if_due()."""
    now = now or datetime.now(timezone.utc)
    if not is_refresh_due(now=now):
        return False
    refresh_data(resume, adapters=adapters)
    _write_last_refresh(now)
    return True


# "internacional" first -- see _TIER_META's comment: it's the newest,
# explicitly-requested focus. It's also cross-cutting (a listing can be
# here AND in its normal company tier -- see group_by_tier()), which is
# why _EXCLUSIVE_TIER_KEYS exists separately below: that's the set whose
# sizes actually partition every relevant listing exactly once, used for
# the "vagas no total" stat so it doesn't double-count.
_TIER_KEYS = ("internacional", "banco", "fintech", "bigtech", "startup", "outras")
_EXCLUSIVE_TIER_KEYS = ("banco", "fintech", "bigtech", "startup", "outras")


def _current_tiers() -> dict[str, list[JobListing]]:
    with _tiers_lock:
        return _tiers or {tier: [] for tier in _TIER_KEYS}


def _esc(s: str | None) -> str:
    return html.escape(s or "", quote=True)


def _render_row(listing: JobListing, applied_log: dict[str, dict]) -> str:
    from sites.job_matching import has_international_signal, has_junior_signal, is_in_target_region, is_remote

    site_label = _SITE_LABELS.get(listing.site_name, listing.site_name)
    key = f"{listing.site_name}:{listing.external_id}"
    applied = applied_log.get(listing.url)
    badges = [f'<span class="site-badge site-{_esc(listing.site_name)}">{_esc(site_label)}</span>']
    junior = has_junior_signal(listing.title, listing.snippet)
    if junior:
        badges.append('<span class="junior-badge">JÚNIOR</span>')
    if is_in_target_region(listing.location):
        badges.append('<span class="site-badge" style="background:var(--surface-3);color:var(--accent-bright);">perto de você</span>')
    elif is_remote(listing.title, listing.snippet, listing.location):
        badges.append('<span class="site-badge" style="background:var(--surface-3);color:var(--accent-bright);">home office</span>')
    # 2026-09-05: on top of the looser "home office" badge above, flag
    # listings that ALSO show a real international signal (foreign
    # currency, "global"/"international" framing) -- helps Nicholas spot
    # the genuinely international ones inside the broader, cross-cutting
    # "internacional" tier at a glance, without gating that tier itself
    # on this stricter signal (see group_by_tier()'s docstring).
    if has_international_signal(listing.title, listing.snippet):
        badges.append('<span class="site-badge" style="background:var(--violet-soft);color:var(--violet);">🌎 internacional</span>')
    if applied:
        badges.append('<span class="applied-badge">✅ CANDIDATURA ENVIADA</span>')

    is_gupy = listing.site_name == "gupy"
    if applied:
        # Já enviada de verdade (ver sites/application_log.py) -- sem
        # botões de ação pra não arriscar reenviar por engano; a data
        # vem do próprio registro, nunca adivinhada.
        sent_date = _esc(_format_applied_date(applied.get("submitted_at")))
        apply_actions = f'<span class="applied-note">Enviada em {sent_date}.</span>'
    elif is_gupy:
        apply_actions = (
            f'<button class="action-btn" type="button" onclick="verificarVaga(this, \'{_esc(listing.url)}\')">Verificar</button>'
            f'<button class="action-btn warn" type="button" onclick="continuarCandidatura(this, \'{_esc(listing.url)}\')">Enviar candidatura</button>'
        )
    else:
        apply_actions = '<span style="font-size:12px;color:var(--text-faint);">Verificação automática só existe pro Gupy por enquanto.</span>'

    return f"""<li class="row{' row-junior' if junior else ''}{' row-applied' if applied else ''}">
        <label class="row-check">
          <input type="checkbox" data-key="{_esc(key)}" data-url="{_esc(listing.url)}" onchange="onCheck(this)" aria-label="Selecionar {_esc(listing.title)}">
        </label>
        <div class="row-body">
          <div class="badges-line">{''.join(badges)}</div>
          <p class="company-name">{_esc(listing.company) or 'empresa não identificada'}</p>
          <a class="row-title" href="{_esc(listing.url)}" target="_blank" rel="noopener">{_esc(listing.title)}</a>
          <div class="row-meta"><span>{_esc(listing.location) or 'localização não informada'}</span></div>
          <div class="action-row">
            <a class="action-btn primary" href="{_esc(listing.url)}" target="_blank" rel="noopener">Ver vaga &rarr;</a>
            {apply_actions}
          </div>
          <div class="result-box"></div>
        </div>
      </li>"""


def _format_applied_date(iso_timestamp: str | None) -> str:
    """dd/mm/aaaa from a stored ISO 8601 UTC timestamp -- falls back to
    the raw stored value (never crashes the whole page render) if it's
    ever missing or in an unexpected shape."""
    if not iso_timestamp:
        return "data desconhecida"
    try:
        return datetime.fromisoformat(iso_timestamp).strftime("%d/%m/%Y")
    except ValueError:
        return iso_timestamp


def _render_section(tier: str, listings: list[JobListing], applied_log: dict[str, dict]) -> str:
    meta = _TIER_META[tier]
    body = (
        '<p class="empty-note">Nenhuma vaga relevante nesta categoria ainda -- clique em "Atualizar vagas agora".</p>'
        if not listings
        else '<ul class="list">' + "".join(_render_row(l, applied_log) for l in listings) + "</ul>"
    )
    return (
        f'<section class="tier-section" data-tier="{tier}">'
        f'<h2 class="section-heading"><span class="tier-badge tier-{tier}">{meta["emoji"]} {meta["label"]}</span></h2>'
        f'<p class="section-sub">{_esc(meta["sub"])} &middot; {len(listings)} vaga(s)</p>'
        f"{body}</section>"
    )


# 2026-08-21, "deixe o site responsivo!" -- open_job_portal() now opens
# the page immediately and runs the first search in a background
# thread (see tools.py), which fixed the page being unreachable for up
# to an hour, but left a new, real gap: the page never updated itself
# once that search finished -- Nicholas had to know to hit Cmd+R
# himself. This script polls /api/status every few seconds ONLY while
# _tiers is still None (the "haven't fetched anything yet at all" case,
# not "refresh finished and found 0 results" -- see _current_tiers()),
# and reloads once real data exists. Deliberately NOT wired to
# "Atualizar vagas agora" (that already reloads itself on its own
# fetch's completion, synchronously, no polling needed there).
_POLL_SCRIPT = """<script>
(function () {
  var iv = setInterval(function () {
    fetch("/api/status").then(function (r) { return r.json(); }).then(function (data) {
      if (data.ready) { clearInterval(iv); window.location.reload(); }
    }).catch(function () {});
  }, 4000);
})();
</script>"""


def render_page() -> str:
    from sites.application_log import load_applications_log

    tiers = _current_tiers()
    with _tiers_lock:
        still_searching = _tiers is None
    applied_log = load_applications_log()
    # .get(tier, []) throughout -- "outras" is only populated by a real
    # refresh_data() call (include_other=True); older/injected _tiers
    # dicts (tests, or a page load before the first refresh finishes)
    # may not have it yet, and that must render as empty, not crash.
    sections = "".join(_render_section(tier, tiers.get(tier, []), applied_log) for tier in _TIER_KEYS)
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.format(
        favicon_link=_FAVICON_LINK_PATH.read_text(encoding="utf-8"),
        # _EXCLUSIVE_TIER_KEYS, not _TIER_KEYS -- "internacional" is
        # cross-cutting (see group_by_tier()'s docstring) and would
        # double-count listings that also live in a company tier.
        total=sum(len(tiers.get(tier, [])) for tier in _EXCLUSIVE_TIER_KEYS),
        international_count=len(tiers.get("internacional", [])),
        banco_count=len(tiers.get("banco", [])),
        fintech_count=len(tiers.get("fintech", [])),
        bigtech_count=len(tiers.get("bigtech", [])),
        startup_count=len(tiers.get("startup", [])),
        outras_count=len(tiers.get("outras", [])),
        sections=sections,
        polling_script=_POLL_SCRIPT if still_searching else "",
    )


def _dedupe_all_listings(tiers: dict[str, list[JobListing]]) -> dict[str, JobListing]:
    """Maps url -> JobListing across every currently-loaded tier bucket,
    including the cross-cutting "internacional" one -- lets the
    analysis screen show a real company/title for an applied URL that's
    still present in this session's in-memory search, with no second
    network round-trip. setdefault() so the first tier encountered wins
    when a listing legitimately sits in more than one bucket -- the
    JobListing itself is identical either way, only the bucket differs."""
    lookup: dict[str, JobListing] = {}
    for items in tiers.values():
        for listing in items:
            lookup.setdefault(listing.url, listing)
    return lookup


def _render_applied_row(url: str, meta: dict, lookup: dict[str, JobListing]) -> str:
    listing = lookup.get(url)
    site_label = _SITE_LABELS.get(meta.get("site_name"), meta.get("site_name") or "?")
    sent_date = _esc(_format_applied_date(meta.get("submitted_at")))
    if listing is not None:
        company = _esc(listing.company) or "empresa não identificada"
        title_html = f'<a class="row-title" href="{_esc(url)}" target="_blank" rel="noopener">{_esc(listing.title)}</a>'
    else:
        # Real, honest limitation: application_log.py only stores
        # url/site_name/submitted_at (see its own docstring) -- no
        # title/company snapshot. If this session's search hasn't found
        # that URL again (or the listing has since closed), all that's
        # left is the URL itself -- never fabricate a title/company.
        company = "(vaga não está mais nos resultados carregados nesta sessão)"
        title_html = f'<a class="row-title" href="{_esc(url)}" target="_blank" rel="noopener">{_esc(url)}</a>'
    return f"""<li class="row row-applied">
        <div class="row-body">
          <div class="badges-line"><span class="site-badge site-{_esc(meta.get('site_name') or '')}">{_esc(site_label)}</span><span class="applied-badge">✅ ENVIADA</span></div>
          <p class="company-name">{company}</p>
          {title_html}
          <div class="row-meta"><span>Enviada em {sent_date}</span></div>
        </div>
      </li>"""


def render_analysis_page() -> str:
    """2026-09-06, "faça uma tela de analise mostrando vagas já
    inscritas e as pendentes! quero enchergar essa analise e essa
    validação!!!" -- a dedicated screen (GET /analise, linked from the
    main page's top bar) separating what's ALREADY been sent for real
    (sites/application_log.py's durable, cross-restart record, newest
    first) from what's still PENDING (this session's relevant, loaded
    listings that have no application_log entry yet). Reuses
    _render_section()/_render_row() for the pending side -- same
    per-tier grouping, same filter chips/JS, same real apply buttons --
    so this isn't a second, drifting copy of that rendering logic."""
    from sites.application_log import load_applications_log

    tiers = _current_tiers()
    with _tiers_lock:
        still_searching = _tiers is None
    applied_log = load_applications_log()
    lookup = _dedupe_all_listings(tiers)

    # "Já inscritas" -- the whole, real, persistent history, newest
    # submission first (missing timestamps sort last, never crash).
    applied_items = sorted(applied_log.items(), key=lambda kv: kv[1].get("submitted_at") or "", reverse=True)
    applied_rows = "".join(_render_applied_row(url, meta, lookup) for url, meta in applied_items)
    applied_section = (
        '<p class="empty-note">Nenhuma candidatura enviada ainda.</p>'
        if not applied_items
        else f'<ul class="list">{applied_rows}</ul>'
    )

    # "Pendentes" -- this session's loaded listings minus anything
    # already in applied_log, grouped/rendered exactly like the main
    # page (including the cross-cutting "internacional" section).
    pending_by_tier = {tier: [l for l in tiers.get(tier, []) if l.url not in applied_log] for tier in _TIER_KEYS}
    pending_sections = "".join(_render_section(tier, pending_by_tier[tier], applied_log) for tier in _TIER_KEYS)
    # _EXCLUSIVE_TIER_KEYS for the arithmetic, same reasoning as
    # render_page()'s "total" -- "internacional" is cross-cutting and
    # would double-count a listing that's also in its company tier.
    pending_total = sum(len(pending_by_tier[tier]) for tier in _EXCLUSIVE_TIER_KEYS)
    loaded_total = sum(len(tiers.get(tier, [])) for tier in _EXCLUSIVE_TIER_KEYS)
    applied_total = len(applied_log)
    denominator = applied_total + pending_total
    conversion_pct = round(100 * applied_total / denominator) if denominator else 0

    template = _ANALYSIS_TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.format(
        favicon_link=_FAVICON_LINK_PATH.read_text(encoding="utf-8"),
        loaded_count=loaded_total,
        applied_count=applied_total,
        pending_count=pending_total,
        conversion_pct=conversion_pct,
        applied_section=applied_section,
        pending_sections=pending_sections,
        polling_script=_POLL_SCRIPT if still_searching else "",
    )


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002 -- stdlib signature
        pass  # quiet -- runs as a background thread

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._serve_page()
        elif self.path == "/analise":
            self._serve_analysis_page()
        elif self.path == "/portal.css":
            self._serve_static(_CSS_PATH, "text/css; charset=utf-8")
        elif self.path == "/portal.js":
            self._serve_static(_JS_PATH, "application/javascript; charset=utf-8")
        elif self.path == "/api/status":
            self._handle_status()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_static(self, path: Path, content_type: str) -> None:
        # Read fresh from disk on every request, same as _serve_page()
        # -- no caching, so CSS/JS edits take effect on the next reload
        # without restarting the server process.
        body = path.read_text(encoding="utf-8").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_analysis_page(self) -> None:
        body = render_analysis_page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_status(self) -> None:
        # Cheap, read-only poll target for the page's own auto-reload
        # script (_POLL_SCRIPT) -- never triggers a search itself,
        # unlike /api/refresh.
        with _tiers_lock:
            ready = _tiers is not None
        self._write_json({"ready": ready})

    def do_POST(self) -> None:
        if self.path == "/api/check":
            self._handle_json_action(self._do_check)
        elif self.path == "/api/apply":
            self._handle_json_action(self._do_apply)
        elif self.path == "/api/refresh":
            self._handle_refresh()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_page(self) -> None:
        body = render_page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    def _write_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_json_action(self, action) -> None:
        try:
            data = self._read_json_body()
            url = data.get("url", "")
            summary = action(url)
            self._write_json({"summary": summary})
        except Exception as exc:  # noqa: BLE001 -- must always answer the request
            self._write_json({"error": str(exc)}, status=500)

    def _do_check(self, url: str) -> str:
        from assistant.tools import check_job_application

        return check_job_application(url)

    def _do_apply(self, url: str) -> str:
        from assistant.tools import continue_job_application

        # finalize=True -- 2026-08-25, explicit Nicholas request: the
        # portal button now submits for real, not just fills. See this
        # module's docstring and page_template.html's confirm() text.
        return continue_job_application(url, finalize=True)

    def _handle_refresh(self) -> None:
        try:
            # include_linkedin=True -- this is the manually-clicked
            # "Atualizar vagas agora" button, an explicit, attended
            # action (see _portal_adapters()'s docstring for why that
            # distinction matters for LinkedIn specifically).
            tiers = refresh_data(adapters=_portal_adapters(include_linkedin=True))
            self._write_json({tier: len(tiers.get(tier, [])) for tier in _TIER_KEYS})
        except Exception as exc:  # noqa: BLE001
            self._write_json({"error": str(exc)}, status=500)


def start(port: int = 8767) -> int:
    """Starts the server at most once per process -- calling again just
    returns the already-running port, same idempotency as the
    visualizer's server.start().

    2026-08-25, real bug found live: this defaulted to 8766, the exact
    same default as config.XTTS_WORKER_PORT -- if the voice-cloning
    worker happened to be running (or anything else squatting on 8766)
    when the portal tried to start, the bind failed outright
    ("Address already in use") and the portal silently never came up.
    8767 doesn't collide with the visualizer (8765) or the xtts worker
    (8766)."""
    global _server
    with _server_lock:
        if _server is not None:
            return _server.server_address[1]
        server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        threading.Thread(target=server.serve_forever, daemon=True, name="jarvis-job-portal-http").start()
        _server = server
        return server.server_address[1]


def url() -> str:
    return f"http://127.0.0.1:{start()}/"


def open_portal() -> str:
    """Starts the server if needed and opens it in the real default
    browser (macOS `open`, not a WKWebView -- Nicholas explicitly asked
    for his actual browser, "abra no meu navegador")."""
    page_url = url()
    try:
        subprocess.run(["open", page_url], check=False, timeout=5)
    except Exception:
        pass  # server is up regardless -- worst case, tell the user the URL
    return page_url
