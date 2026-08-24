import json
import urllib.error
import urllib.request

import pytest

from visualizer import state
from visualizer import server


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    # server._server is a real ThreadingHTTPServer once started -- reset
    # the reference (not shut it down) so each test binds a fresh
    # OS-assigned ephemeral port (port=0) instead of colliding on 8765.
    monkeypatch.setattr(server, "_server", None)
    monkeypatch.setattr(state, "_subscribers", [])
    monkeypatch.setattr(state, "_current", state.StateEvent(state="idle"))
    monkeypatch.setattr(state, "_current_data", None)


def _read_data_line(resp) -> str:
    while True:
        raw = resp.readline().decode("utf-8").strip()
        if raw.startswith("data: "):
            return raw[len("data: ") :]


def test_start_is_idempotent_within_a_process():
    port1 = server.start(port=0)
    port2 = server.start(port=0)

    assert port1 == port2


def test_serves_the_hud_page():
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers["Content-Type"]
        body = resp.read().decode("utf-8")

    assert "<html" in body.lower()
    assert "J • A • R • V • I • S" in body


def test_unknown_path_is_404():
    port = server.start(port=0)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=5)

    assert exc_info.value.code == 404


def test_events_endpoint_streams_current_state_immediately():
    port = server.start(port=0)
    state.publish("listening")

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/events", timeout=5) as resp:
        assert json.loads(_read_data_line(resp)) == {"type": "state", "state": "listening", "text": ""}


def test_events_endpoint_streams_subsequent_publishes():
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/events", timeout=5) as resp:
        _read_data_line(resp)  # the initial "idle" snapshot -- not under test here
        state.publish("speaking", text="olá, Senhor Nicholas")
        assert json.loads(_read_data_line(resp)) == {
            "type": "state",
            "state": "speaking",
            "text": "olá, Senhor Nicholas",
        }


def test_events_endpoint_streams_current_chart_immediately_after_state():
    port = server.start(port=0)
    state.publish_data("finance", {"title": "Patrimônio", "bars": [{"label": "Inter BR", "value": 100}]})

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/events", timeout=5) as resp:
        _read_data_line(resp)  # the state snapshot always comes first -- not under test here
        assert json.loads(_read_data_line(resp)) == {
            "type": "data",
            "kind": "finance",
            "payload": {"title": "Patrimônio", "bars": [{"label": "Inter BR", "value": 100}]},
        }


def test_events_endpoint_streams_subsequent_chart_publishes():
    port = server.start(port=0)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/events", timeout=5) as resp:
        _read_data_line(resp)  # the initial "idle" state snapshot -- not under test here
        state.publish_data("jobs", {"title": "Vagas", "bars": []})
        assert json.loads(_read_data_line(resp)) == {"type": "data", "kind": "jobs", "payload": {"title": "Vagas", "bars": []}}


def test_url_returns_a_reachable_localhost_address():
    # Pre-seed with an ephemeral port -- url()'s own start() call is
    # idempotent and will just reuse this, avoiding a collision with
    # start()'s real default port (8765) if something else on the machine
    # (e.g. the actual running menu-bar app) already has it bound.
    server.start(port=0)

    result = server.url()

    assert result.startswith("http://127.0.0.1:")
    with urllib.request.urlopen(result, timeout=5) as resp:
        assert resp.status == 200
