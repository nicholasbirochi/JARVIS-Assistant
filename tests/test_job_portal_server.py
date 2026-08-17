import json
import urllib.error
import urllib.request

import pytest

from jarvis.job_portal import server
from jarvis.sites.base import JobListing


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
    from jarvis.assistant import tools

    calls = []
    monkeypatch.setattr(tools, "check_job_application", lambda url: calls.append(url) or "resultado da checagem")
    port = server.start(port=0)

    status, body = _post(port, "/api/check", {"url": "https://empresa.gupy.io/job/xyz"})

    assert status == 200
    assert body["summary"] == "resultado da checagem"
    assert calls == ["https://empresa.gupy.io/job/xyz"]


def test_apply_endpoint_calls_continue_job_application(monkeypatch):
    from jarvis.assistant import tools

    calls = []
    monkeypatch.setattr(tools, "continue_job_application", lambda url: calls.append(url) or "resultado do preenchimento")
    port = server.start(port=0)

    status, body = _post(port, "/api/apply", {"url": "https://empresa.gupy.io/job/xyz"})

    assert status == 200
    assert body["summary"] == "resultado do preenchimento"
    assert calls == ["https://empresa.gupy.io/job/xyz"]


def test_check_endpoint_reports_errors_as_json_500(monkeypatch):
    from jarvis.assistant import tools

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
    def _fake_refresh():
        return {"banco": [make_listing("1", "X")], "fintech": [], "bigtech": [], "startup": []}

    monkeypatch.setattr(server, "refresh_data", _fake_refresh)
    port = server.start(port=0)

    status, body = _post(port, "/api/refresh", {})

    assert status == 200
    assert body == {"banco": 1, "fintech": 0, "bigtech": 0, "startup": 0}


def test_render_page_never_raises_with_no_data():
    # Direct unit-level check, no HTTP -- render_page() must degrade
    # gracefully to the empty state rather than raising when _tiers is
    # still None (before any refresh has ever run in this process).
    page = server.render_page()

    assert "<html" in page.lower()
