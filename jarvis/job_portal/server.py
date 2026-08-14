"""Local-only HTTP server for the job-application portal -- serves a
real, interactive page at `/` whose buttons genuinely run on this Mac
(unlike the earlier Claude Artifact version, which is hosted on
Anthropic's own servers with no path back to local Playwright/JARVIS at
all -- see this module's origin: Nicholas asked to "mude para local...
a gente conseguir fazer as inscrições", after already being told the
Artifact structurally can't do this).

Same pattern as jarvis/visualizer/server.py: plain stdlib http.server,
bound to 127.0.0.1 only, ThreadingHTTPServer so a slow request (real
Playwright automation, 10-30+ seconds) doesn't block other connections.
Different port (8766, not the visualizer's 8765) so both can run at
once.

Routes:
- GET  /            -- the page, rendered fresh from the in-memory
  tiered report (see refresh_data()). Empty state if nothing has been
  fetched yet in this process.
- POST /api/check   -- {"url": "..."} -> jarvis.assistant.tools.
  check_job_application(url) -- read-only, never submits anything.
- POST /api/apply   -- {"url": "..."} -> jarvis.assistant.tools.
  continue_job_application(url) -- a REAL, mutating action (fills a
  live form using the local application profile), gated by the same
  all-or-nothing/never-final-submit rules as everywhere else in this
  project. The browser's own confirm() dialog (in page_template.html)
  is the human-in-the-loop check before this ever fires.
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jarvis.sites.base import JobListing

_TEMPLATE_PATH = Path(__file__).resolve().parent / "page_template.html"

_TIER_META = {
    "banco": {"label": "Bancos", "emoji": "🏦", "sub": "Bancos nomeados (Itaú, Bradesco, Santander, Nubank, BTG e outros)"},
    "bigtech": {"label": "Bigtechs", "emoji": "💻", "sub": "Bigtechs nomeadas (Google, Amazon, Mercado Livre, iFood, Stone e outras)"},
    "startup": {"label": "Startups", "emoji": "🚀", "sub": "Startups/scale-ups nomeadas (Gupy, Hotmart, QuintoAndar, BairesDev e outras)"},
}

_SITE_LABELS = {
    "infojobs": "InfoJobs",
    "catho": "Catho",
    "gupy": "Gupy",
    "amazon_jobs": "Amazon Jobs",
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
}

_server: ThreadingHTTPServer | None = None
_server_lock = threading.Lock()
_tiers: dict[str, list[JobListing]] | None = None
_tiers_lock = threading.Lock()


def _portal_adapters() -> dict[str, object]:
    from jarvis.sites.amazon_jobs import AmazonJobsAdapter
    from jarvis.sites.catho import CathoAdapter
    from jarvis.sites.gupy import GupyAdapter
    from jarvis.sites.infojobs import InfoJobsAdapter

    return {
        "infojobs": InfoJobsAdapter(),
        "catho": CathoAdapter(),
        "gupy": GupyAdapter(),
        "amazon_jobs": AmazonJobsAdapter(),
    }


def refresh_data(resume=None, *, adapters: dict[str, object] | None = None) -> dict[str, list[JobListing]]:
    """Runs a real, fresh search (jarvis.job_search.run_job_search) and
    tiers the combined local+remote relevant results via
    jarvis.sites.job_matching.group_by_tier(). Stores the result for
    subsequent page renders/route handlers. resume/adapters are
    injectable for tests; production calls load the real résumé and use
    _portal_adapters()."""
    from jarvis.job_search import run_job_search
    from jarvis.sites.job_matching import group_by_tier

    if resume is None:
        from jarvis.resume import store

        resume = store.load()
    if adapters is None:
        adapters = _portal_adapters()

    report = run_job_search(resume, adapters=adapters)
    combined = report.local + report.remote
    tiers = group_by_tier(combined)

    with _tiers_lock:
        global _tiers
        _tiers = tiers
    return tiers


def _current_tiers() -> dict[str, list[JobListing]]:
    with _tiers_lock:
        return _tiers or {"banco": [], "bigtech": [], "startup": []}


def _esc(s: str | None) -> str:
    return html.escape(s or "", quote=True)


def _render_row(listing: JobListing) -> str:
    from jarvis.sites.job_matching import has_junior_signal, is_in_target_region, is_remote

    site_label = _SITE_LABELS.get(listing.site_name, listing.site_name)
    key = f"{listing.site_name}:{listing.external_id}"
    badges = [f'<span class="site-badge site-{_esc(listing.site_name)}">{_esc(site_label)}</span>']
    junior = has_junior_signal(listing.title, listing.snippet)
    if junior:
        badges.append('<span class="junior-badge">JÚNIOR</span>')
    if is_in_target_region(listing.location):
        badges.append('<span class="site-badge" style="background:var(--tag-bg);color:var(--tag-text);">perto de você</span>')
    elif is_remote(listing.title, listing.snippet, listing.location):
        badges.append('<span class="site-badge" style="background:var(--tag-bg);color:var(--tag-text);">home office</span>')

    is_gupy = listing.site_name == "gupy"
    apply_actions = (
        f'<button class="action-btn" type="button" onclick="verificarVaga(this, \'{_esc(listing.url)}\')">Verificar</button>'
        f'<button class="action-btn warn" type="button" onclick="continuarCandidatura(this, \'{_esc(listing.url)}\')">Continuar candidatura</button>'
        if is_gupy
        else '<span style="font-size:12px;color:var(--text-muted);">Verificação automática só existe pro Gupy por enquanto.</span>'
    )

    return f"""<li class="row{' row-junior' if junior else ''}">
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


def _render_section(tier: str, listings: list[JobListing]) -> str:
    meta = _TIER_META[tier]
    body = (
        '<p class="empty-note">Nenhuma vaga relevante nesta categoria ainda -- clique em "Atualizar vagas agora".</p>'
        if not listings
        else '<ul class="list">' + "".join(_render_row(l) for l in listings) + "</ul>"
    )
    return (
        f'<section class="tier-section" data-tier="{tier}">'
        f'<h2 class="section-heading"><span class="tier-badge tier-{tier}">{meta["emoji"]} {meta["label"]}</span></h2>'
        f'<p class="section-sub">{_esc(meta["sub"])} &middot; {len(listings)} vaga(s)</p>'
        f"{body}</section>"
    )


def render_page() -> str:
    tiers = _current_tiers()
    banco, bigtech, startup = tiers["banco"], tiers["bigtech"], tiers["startup"]
    sections = "".join(
        _render_section(tier, tiers[tier]) for tier in ("banco", "bigtech", "startup")
    )
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.format(
        total=len(banco) + len(bigtech) + len(startup),
        banco_count=len(banco),
        bigtech_count=len(bigtech),
        startup_count=len(startup),
        sections=sections,
    )


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002 -- stdlib signature
        pass  # quiet -- runs as a background thread

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._serve_page()
        else:
            self.send_response(404)
            self.end_headers()

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
        from jarvis.assistant.tools import check_job_application

        return check_job_application(url)

    def _do_apply(self, url: str) -> str:
        from jarvis.assistant.tools import continue_job_application

        return continue_job_application(url)

    def _handle_refresh(self) -> None:
        try:
            tiers = refresh_data()
            self._write_json({"banco": len(tiers["banco"]), "bigtech": len(tiers["bigtech"]), "startup": len(tiers["startup"])})
        except Exception as exc:  # noqa: BLE001
            self._write_json({"error": str(exc)}, status=500)


def start(port: int = 8766) -> int:
    """Starts the server at most once per process -- calling again just
    returns the already-running port, same idempotency as the
    visualizer's server.start()."""
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
