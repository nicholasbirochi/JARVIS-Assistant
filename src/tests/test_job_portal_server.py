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


def make_listing(external_id, title, *, site_name="gupy", company="Itaú", location="São Paulo - SP") -> JobListing:
    return JobListing(
        site_name=site_name,
        external_id=external_id,
        title=title,
        company=company,
        location=location,
        url=f"https://{site_name}.example.com/{external_id}",
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
    assert "Continuar candidatura" in body  # gupy listing -> real apply button shown


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


def test_apply_endpoint_calls_continue_job_application(monkeypatch):
    from assistant import tools

    calls = []
    monkeypatch.setattr(tools, "continue_job_application", lambda url: calls.append(url) or "resultado do preenchimento")
    port = server.start(port=0)

    status, body = _post(port, "/api/apply", {"url": "https://empresa.gupy.io/job/xyz"})

    assert status == 200
    assert body["summary"] == "resultado do preenchimento"
    assert calls == ["https://empresa.gupy.io/job/xyz"]


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
    assert body == {"banco": 1, "fintech": 0, "bigtech": 0, "startup": 0, "outras": 0}
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
