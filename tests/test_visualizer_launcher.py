import pytest

from jarvis import config
from jarvis.visualizer import launcher, server


class FakePopen:
    def __init__(self, args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self._returncode = None

    def poll(self):
        return self._returncode

    def finish(self, code=0):
        self._returncode = code


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "_process", None)
    monkeypatch.setattr(server, "url", lambda: "http://127.0.0.1:8765/")
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)


def test_opens_default_browser_when_chromium_unavailable(monkeypatch):
    monkeypatch.setattr(launcher, "_chromium_executable_path", lambda: None)
    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url))

    launcher.open_window()

    assert opened == ["http://127.0.0.1:8765/"]


def test_launches_chromium_in_app_mode_when_available(monkeypatch):
    monkeypatch.setattr(launcher, "_chromium_executable_path", lambda: "/path/to/chromium")
    created = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda args, **kw: created.append(FakePopen(args, **kw)) or created[-1])

    launcher.open_window()

    assert len(created) == 1
    assert created[0].args[0] == "/path/to/chromium"
    assert "--app=http://127.0.0.1:8765/" in created[0].args
    assert any(a.startswith("--user-data-dir=") for a in created[0].args)


def test_does_not_relaunch_while_a_window_is_still_open(monkeypatch):
    monkeypatch.setattr(launcher, "_chromium_executable_path", lambda: "/path/to/chromium")
    created = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda args, **kw: created.append(FakePopen(args, **kw)) or created[-1])

    launcher.open_window()
    launcher.open_window()

    assert len(created) == 1


def test_relaunches_after_the_previous_window_was_closed(monkeypatch):
    monkeypatch.setattr(launcher, "_chromium_executable_path", lambda: "/path/to/chromium")
    created = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda args, **kw: created.append(FakePopen(args, **kw)) or created[-1])

    launcher.open_window()
    created[0].finish()  # user closed the window
    launcher.open_window()

    assert len(created) == 2


def test_chromium_executable_path_returns_none_without_playwright_installed(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "playwright.sync_api":
            raise ImportError("no playwright")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert launcher._chromium_executable_path() is None
