import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

import config
from job_portal import server
from sites.base import JobListing


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(server, "_server", None)
    monkeypatch.setattr(server, "_tiers", None)


def make_listing(
    external_id, title, *, site_name="gupy", company="Itaú", location="São Paulo - SP", snippet=None
) -> JobListing:
    return JobListing(
        site_name=site_name,
        external_id=external_id,
        title=title,
        company=company,
        location=location,
        url=f"https://{site_name}.example.com/{external_id}",
        snippet=snippet,
    )


def _post(port, path, payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def test_start_is_idempotent_within_a_process():
    port1 = server.start(port=0)
    port2 = server.start(port=0)

    assert port1 == port2


def test_serves_empty_state_when_no_data_fetched_yet():
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        assert resp.status == 200
        body = resp.read().decode("utf-8")

    assert "Nenhuma vaga relevante" in body
    assert "0" in body  # stat strip shows 0 total


def test_serves_the_page_with_real_tier_data(monkeypatch):
    monkeypatch.setattr(
        server,
        "_tiers",
        {
            "banco": [make_listing("1", "Analista de Dados Júnior", company="Itaú")],
            "fintech": [],
            "bigtech": [],
            "startup": [],
        },
    )
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert "Analista de Dados Júnior" in body
    assert "Itaú" in body
    assert "JÚNIOR" in body
    assert "Enviar candidatura" in body  # gupy listing -> real apply button shown


def test_serves_the_fintech_tier(monkeypatch):
    monkeypatch.setattr(
        server,
        "_tiers",
        {
            "banco": [],
            "fintech": [make_listing("1", "Analista de Dados", company="Nubank")],
            "bigtech": [],
            "startup": [],
        },
    )
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert "Nubank" in body
    assert "Fintechs" in body
    assert 'data-tier="fintech"' in body


def test_serves_the_outras_tier(monkeypatch):
    # Added 2026-08-17: real volume for "quero pelo menos mais de 200
    # vagas" -- relevant listings at a company not in the curated lists
    # go here instead of being dropped.
    monkeypatch.setattr(
        server,
        "_tiers",
        {
            "banco": [],
            "fintech": [],
            "bigtech": [],
            "startup": [],
            "outras": [make_listing("1", "Analista de Dados", company="Empresa Qualquer Ltda")],
        },
    )
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert "Empresa Qualquer Ltda" in body
    assert "Outras empresas" in body
    assert 'data-tier="outras"' in body


def test_serves_the_international_tier(monkeypatch):
    # 2026-09-05, "quero candidaturas focadas nesse tipo de vagas
    # também! internacionais remotas!!!!" -- new, cross-cutting tier
    # (see job_matching.group_by_tier()'s docstring).
    monkeypatch.setattr(
        server,
        "_tiers",
        {
            "internacional": [make_listing("1", "Data Analyst", company="BairesDev", snippet="100% remoto")],
            "banco": [],
            "fintech": [],
            "bigtech": [],
            "startup": [],
        },
    )
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert "BairesDev" in body
    assert "Remoto/Internacional" in body
    assert 'data-tier="internacional"' in body


def test_total_stat_does_not_double_count_a_cross_tiered_listing(monkeypatch):
    # "internacional" is cross-cutting -- the same listing also sits in
    # its normal company tier (here "banco"). The "vagas no total" stat
    # must still read 1, not 2.
    listing = make_listing("1", "Analista de Dados", company="Itaú", snippet="100% remoto")
    monkeypatch.setattr(
        server,
        "_tiers",
        {"internacional": [listing], "banco": [listing], "fintech": [], "bigtech": [], "startup": [], "outras": []},
    )

    page = server.render_page()

    assert '<div class="n">1</div><div class="l">vagas no total</div>' in page


def test_row_shows_international_badge_when_listing_has_the_signal(monkeypatch):
    monkeypatch.setattr(
        server,
        "_tiers",
        {
            "internacional": [
                make_listing("1", "Data Analyst", company="BairesDev", snippet="Cliente internacional, salário em USD")
            ],
            "banco": [],
            "fintech": [],
            "bigtech": [],
            "startup": [],
        },
    )
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert "🌎 internacional" in body


def test_row_omits_international_badge_without_the_signal(monkeypatch):
    monkeypatch.setattr(
        server,
        "_tiers",
        {
            "internacional": [make_listing("1", "Analista de Dados", company="Empresa Nacional", snippet="100% remoto")],
            "banco": [],
            "fintech": [],
            "bigtech": [],
            "startup": [],
        },
    )
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert "🌎 internacional" not in body


def test_render_page_works_when_outras_key_is_missing(monkeypatch):
    # Older/injected _tiers dicts (or a page load before the first real
    # refresh_data() call ever populates "outras") must render fine, not
    # crash with a KeyError.
    monkeypatch.setattr(server, "_tiers", {"banco": [], "fintech": [], "bigtech": [], "startup": []})

    page = server.render_page()

    assert "<html" in page.lower()


def test_non_gupy_listing_does_not_offer_continue_button(monkeypatch):
    monkeypatch.setattr(
        server,
        "_tiers",
        {"banco": [], "fintech": [], "bigtech": [], "startup": [make_listing("1", "X", site_name="catho")]},
    )
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    # The page's own explanatory subtitle mentions the feature by name --
    # check for the actual per-row action button (its onclick handler),
    # not just the phrase anywhere on the page.
    assert "continuarCandidatura(this" not in body
    assert "só existe pro Gupy por enquanto" in body


def test_already_applied_listing_shows_badge_and_no_apply_button(monkeypatch, tmp_path):
    # 2026-08-25, real Nicholas request: the portal should show which
    # jobs were already really submitted (sites/application_log.py),
    # not offer to apply again.
    from sites import application_log

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    listing = make_listing("1", "Analista de Dados Júnior")
    application_log.record_application(listing.url, "gupy")
    monkeypatch.setattr(server, "_tiers", {"banco": [listing], "fintech": [], "bigtech": [], "startup": []})
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert "CANDIDATURA ENVIADA" in body
    assert "continuarCandidatura(this" not in body
    assert "Enviada em" in body


def test_manually_applied_listing_shows_a_distinct_manual_badge(monkeypatch, tmp_path):
    # 2026-09-07, "me candidatei a todas as vagas de banco e as
    # Fintechs!" -- Nicholas applying by hand is just as real, but the
    # badge says so distinctly since only source="jarvis" was actually
    # driven and confirmed by code.
    from sites import application_log

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    listing = make_listing("1", "Analista de Dados Júnior")
    application_log.record_application(listing.url, "gupy", source="manual")
    monkeypatch.setattr(server, "_tiers", {"banco": [listing], "fintech": [], "bigtech": [], "startup": []})
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert "CANDIDATURA ENVIADA (manual)" in body


def test_jarvis_applied_listing_does_not_show_the_manual_suffix(monkeypatch, tmp_path):
    from sites import application_log

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    listing = make_listing("1", "Analista de Dados Júnior")
    application_log.record_application(listing.url, "gupy")
    monkeypatch.setattr(server, "_tiers", {"banco": [listing], "fintech": [], "bigtech": [], "startup": []})
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert "CANDIDATURA ENVIADA" in body
    assert "CANDIDATURA ENVIADA (manual)" not in body


def test_not_yet_applied_listing_still_shows_the_apply_button(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    listing = make_listing("1", "Analista de Dados Júnior")
    monkeypatch.setattr(server, "_tiers", {"banco": [listing], "fintech": [], "bigtech": [], "startup": []})
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert "CANDIDATURA ENVIADA" not in body
    assert "continuarCandidatura(this" in body


# --- shared static assets (portal.css / portal.js) ------------------------
#
# 2026-09-06: extracted out of page_template.html's inline <style>/<script>
# so the new /analise screen can share them instead of duplicating ~280
# lines of CSS/JS across two files (a real drift risk on a UI that's
# already been tweaked several times this project).


def test_main_page_links_to_the_shared_css_and_js_files():
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert '<link rel="stylesheet" href="/portal.css">' in body
    assert '<script src="/portal.js"></script>' in body


def test_main_page_links_to_the_analysis_screen():
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert 'href="/analise"' in body


def test_portal_css_route_serves_real_css():
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/portal.css", timeout=5) as resp:
        assert resp.status == 200
        assert "text/css" in resp.headers["Content-Type"]
        body = resp.read().decode("utf-8")

    assert ".stat-strip" in body


def test_portal_js_route_serves_real_js():
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/portal.js", timeout=5) as resp:
        assert resp.status == 200
        assert "javascript" in resp.headers["Content-Type"]
        body = resp.read().decode("utf-8")

    assert "window.toggleTier" in body


# --- /analise (análise: enviadas vs. pendentes) ----------------------------
#
# 2026-09-06, "faça uma tela de analise mostrando vagas já inscritas e as
# pendentes! quero enchergar essa analise e essa validação!!!"


def test_analysis_page_renders_with_no_data(monkeypatch, tmp_path):
    # Isolated DATA_DIR -- without this, a real applications_sent.json
    # already sitting in the project's actual data dir (real submissions
    # tracked across real sessions) would make this "empty state" test
    # fail, exactly as happened live 2026-09-07 once the first 28 real
    # entries existed.
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/analise", timeout=5) as resp:
        assert resp.status == 200
        body = resp.read().decode("utf-8")

    assert "<html" in body.lower()
    assert "Nenhuma candidatura enviada ainda." in body


def test_analysis_page_shows_a_real_applied_job_with_company_and_date(monkeypatch, tmp_path):
    from sites import application_log

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    listing = make_listing("1", "Analista de Dados Júnior", company="Itaú")
    monkeypatch.setattr(server, "_tiers", {"banco": [listing], "fintech": [], "bigtech": [], "startup": []})
    application_log.record_application(listing.url, "gupy")
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/analise", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert "Analista de Dados Júnior" in body
    assert "Itaú" in body
    assert "✅ ENVIADA" in body
    assert "Enviada em" in body


def test_analysis_page_shows_manual_badge_for_manually_applied_jobs(monkeypatch, tmp_path):
    from sites import application_log

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    listing = make_listing("1", "Analista de Dados Júnior", company="Itaú")
    monkeypatch.setattr(server, "_tiers", {"banco": [listing], "fintech": [], "bigtech": [], "startup": []})
    application_log.record_application(listing.url, "gupy", source="manual")
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/analise", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert "✅ ENVIADA (manual)" in body


def test_analysis_page_falls_back_to_the_bare_url_when_the_applied_listing_is_gone(monkeypatch, tmp_path):
    # Real, honest limitation: application_log.py only stores url/
    # site_name/submitted_at -- if this session's search hasn't (yet, or
    # ever again) turned up that same URL, there's no title/company to
    # show. Must say so plainly, never fabricate one.
    from sites import application_log

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "_tiers", {"banco": [], "fintech": [], "bigtech": [], "startup": []})
    application_log.record_application("https://empresa.gupy.io/job/velha", "gupy")
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/analise", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert "https://empresa.gupy.io/job/velha" in body
    assert "não está mais nos resultados carregados" in body


def test_analysis_page_lists_a_pending_job_not_yet_applied(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    listing = make_listing("1", "Analista de Dados Júnior", company="Nubank")
    monkeypatch.setattr(server, "_tiers", {"banco": [], "fintech": [listing], "bigtech": [], "startup": []})
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/analise", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert "Nubank" in body
    assert 'data-tier="fintech"' in body


def test_analysis_page_excludes_an_already_applied_job_from_the_pending_lists(monkeypatch, tmp_path):
    from sites import application_log

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    listing = make_listing("1", "Analista de Dados Júnior", company="Itaú")
    monkeypatch.setattr(server, "_tiers", {"banco": [listing], "fintech": [], "bigtech": [], "startup": []})
    application_log.record_application(listing.url, "gupy")
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/analise", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    # Present once (in "já inscritas"), not a second time in "pendentes".
    assert body.count("Analista de Dados Júnior") == 1


def test_analysis_page_kpi_counts_are_correct(monkeypatch, tmp_path):
    from sites import application_log

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    applied = make_listing("1", "Vaga Enviada", company="Itaú")
    pending = make_listing("2", "Vaga Pendente", company="Nubank")
    monkeypatch.setattr(server, "_tiers", {"banco": [applied], "fintech": [pending], "bigtech": [], "startup": []})
    application_log.record_application(applied.url, "gupy")
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/analise", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert '<div class="n">2</div><div class="l">vagas carregadas</div>' in body
    assert '<div class="n">1</div><div class="l">✅ já inscritas</div>' in body
    assert '<div class="n">1</div><div class="l">⏳ pendentes</div>' in body
    assert '<div class="n">50%</div><div class="l">taxa de envio</div>' in body


def test_analysis_page_links_back_to_the_main_page():
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/analise", timeout=5) as resp:
        body = resp.read().decode("utf-8")

    assert 'href="/"' in body


def test_unknown_path_is_404():
    port = server.start(port=0)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=5)

    assert exc_info.value.code == 404


def test_check_endpoint_calls_check_job_application(monkeypatch):
    from assistant import tools

    calls = []
    monkeypatch.setattr(tools, "check_job_application", lambda url: calls.append(url) or "resultado da checagem")
    port = server.start(port=0)

    status, body = _post(port, "/api/check", {"url": "https://empresa.gupy.io/job/xyz"})

    assert status == 200
    assert body["summary"] == "resultado da checagem"
    assert calls == ["https://empresa.gupy.io/job/xyz"]


def test_apply_endpoint_calls_continue_job_application_with_finalize_true(monkeypatch):
    # 2026-08-25, real behavior change at Nicholas's explicit request:
    # the portal's apply button now submits for real, not just fills --
    # this is the one caller of continue_job_application() that must
    # always pass finalize=True (voice/text calls it with the default
    # finalize=False -- see assistant/tools.py's docstring for why the
    # two callers deliberately differ).
    from assistant import tools

    calls = []
    monkeypatch.setattr(
        tools,
        "continue_job_application",
        lambda url, *, finalize=False: calls.append((url, finalize)) or "resultado do envio",
    )
    port = server.start(port=0)

    status, body = _post(port, "/api/apply", {"url": "https://empresa.gupy.io/job/xyz"})

    assert status == 200
    assert body["summary"] == "resultado do envio"
    assert calls == [("https://empresa.gupy.io/job/xyz", True)]


def test_check_endpoint_reports_errors_as_json_500(monkeypatch):
    from assistant import tools

    def _boom(url):
        raise RuntimeError("falhou de verdade")

    monkeypatch.setattr(tools, "check_job_application", _boom)
    port = server.start(port=0)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(port, "/api/check", {"url": "https://empresa.gupy.io/job/xyz"})

    assert exc_info.value.code == 500
    body = json.loads(exc_info.value.read().decode("utf-8"))
    assert "falhou de verdade" in body["error"]


def test_refresh_endpoint_calls_refresh_data_and_returns_counts(monkeypatch):
    seen_adapters = []

    def _fake_refresh(*, adapters=None):
        seen_adapters.append(adapters)
        return {"banco": [make_listing("1", "X")], "fintech": [], "bigtech": [], "startup": []}

    monkeypatch.setattr(server, "refresh_data", _fake_refresh)
    port = server.start(port=0)

    status, body = _post(port, "/api/refresh", {})

    assert status == 200
    assert body == {"internacional": 0, "banco": 1, "fintech": 0, "bigtech": 0, "startup": 0, "outras": 0}
    # The manually-clicked "Atualizar vagas agora" button is exactly the
    # explicit, attended action that earns the extended (LinkedIn-
    # included) adapter set -- see _portal_adapters()'s docstring.
    assert "linkedin" in seen_adapters[0]


def test_portal_adapters_excludes_linkedin_by_default():
    assert "linkedin" not in server._portal_adapters()


def test_portal_adapters_includes_linkedin_when_requested():
    assert "linkedin" in server._portal_adapters(include_linkedin=True)


def test_portal_adapters_never_includes_indeed():
    # Real, confirmed live 2026-08-11 (see indeed.py): a handful of
    # search_jobs() calls in a short window triggers a real IP-level
    # block -- exactly this sweep's pattern (12+ terms back to back).
    assert "indeed" not in server._portal_adapters()
    assert "indeed" not in server._portal_adapters(include_linkedin=True)


def test_portal_adapters_always_includes_remoteok():
    # Unlike LinkedIn/Indeed, RemoteOK (2026-08-19) is a real public JSON
    # API with no anti-bot layer or account-adjacent risk -- safe on the
    # unattended daily path, no opt-in needed.
    assert "remoteok" in server._portal_adapters()
    assert "remoteok" in server._portal_adapters(include_linkedin=True)


def test_portal_adapters_always_includes_weworkremotely():
    assert "weworkremotely" in server._portal_adapters()
    assert "weworkremotely" in server._portal_adapters(include_linkedin=True)


def test_render_page_never_raises_with_no_data():
    # Direct unit-level check, no HTTP -- render_page() must degrade
    # gracefully to the empty state rather than raising when _tiers is
    # still None (before any refresh has ever run in this process).
    page = server.render_page()

    assert "<html" in page.lower()


# --- /api/status + the page's own auto-reload script ---------------------
#
# 2026-08-21, "deixe o site responsivo!": open_job_portal() opens the
# page immediately and searches in a background thread (fixing "o site
# continua sem funcionar" -- it used to be unreachable for the whole
# search), but that left the page never updating itself once the search
# actually finished. This is the fix: the page polls /api/status while
# _tiers is still None, and reloads once it isn't.


def test_render_page_includes_the_polling_script_while_still_searching():
    server._tiers = None

    page = server.render_page()

    assert "/api/status" in page


def test_render_page_omits_the_polling_script_once_data_exists():
    # Even an empty-but-real result (a search that genuinely found
    # nothing) must stop polling -- "still None" is the only "keep
    # polling" signal, not "zero listings".
    server._tiers = {tier: [] for tier in server._TIER_KEYS}

    page = server.render_page()

    assert "/api/status" not in page


def test_status_endpoint_reports_not_ready_before_any_refresh():
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    assert resp.status == 200
    assert body == {"ready": False}


def test_status_endpoint_reports_ready_once_tiers_exist():
    port = server.start(port=0)
    server._tiers = {tier: [] for tier in server._TIER_KEYS}

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    assert body == {"ready": True}


def test_status_endpoint_never_triggers_a_search(monkeypatch):
    # Unlike /api/refresh, polling this must be cheap and read-only.
    port = server.start(port=0)
    calls = []
    monkeypatch.setattr(server, "refresh_data", lambda **kwargs: calls.append(1))

    urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5).read()

    assert calls == []


# --- daily refresh (is_refresh_due / refresh_if_due) ---------------------
#
# Own tracking file (portal_last_refresh.json), independent from
# job_search.py's is_daily_search_due() -- the deep portal sweep and the
# shallow voice/text report run on separate schedules.


def make_resume():
    from resume.schema import Bilingual, PersonalInfo, Resume

    return Resume(
        personal_info=PersonalInfo(full_name="Nicholas Birochi", phone=None, email="n@example.com"),
        summary=Bilingual(pt="Resumo."),
    )


class FakeAdapter:
    def __init__(self, listings=None):
        self._listings = listings or []
        self.calls: list[str] = []

    def search_jobs(self, query, *, max_results=20):
        self.calls.append(query)
        return self._listings


def test_is_refresh_due_true_when_never_run(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    assert server.is_refresh_due() is True


def test_is_refresh_due_false_within_24h(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    server.refresh_if_due(make_resume(), adapters={"infojobs": FakeAdapter()}, now=now)

    assert server.is_refresh_due(now=now + timedelta(hours=2)) is False


def test_is_refresh_due_true_after_24h(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    server.refresh_if_due(make_resume(), adapters={"infojobs": FakeAdapter()}, now=now)

    assert server.is_refresh_due(now=now + timedelta(hours=25)) is True


def test_refresh_if_due_skips_a_second_call_the_same_day(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    adapter = FakeAdapter()
    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)

    first = server.refresh_if_due(make_resume(), adapters={"infojobs": adapter}, now=now)
    calls_after_first = len(adapter.calls)
    second = server.refresh_if_due(make_resume(), adapters={"infojobs": adapter}, now=now + timedelta(hours=1))

    assert first is True
    assert second is False
    assert len(adapter.calls) == calls_after_first  # no new searches ran


def test_refresh_if_due_runs_again_after_24h(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    adapter = FakeAdapter()
    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)

    server.refresh_if_due(make_resume(), adapters={"infojobs": adapter}, now=now)
    second = server.refresh_if_due(make_resume(), adapters={"infojobs": adapter}, now=now + timedelta(hours=25))

    assert second is True


def test_refresh_if_due_actually_populates_tiers(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "_tiers", None)
    bank_listing = make_listing("1", "Analista de Dados", company="Itaú", location="São Bernardo do Campo - SP")

    server.refresh_if_due(make_resume(), adapters={"infojobs": FakeAdapter([bank_listing])})

    assert len(server._tiers["banco"]) == 1
