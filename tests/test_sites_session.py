from jarvis import config
from jarvis.sites import session


def test_state_path_is_scoped_per_site(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SITES_STATE_DIR", tmp_path)

    assert session.state_path("gupy") == tmp_path / "gupy_state.json"
    assert session.state_path("catho") == tmp_path / "catho_state.json"


def test_has_saved_session_false_when_never_logged_in(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SITES_STATE_DIR", tmp_path)

    assert session.has_saved_session("gupy") is False


def test_has_saved_session_true_once_state_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SITES_STATE_DIR", tmp_path)
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "gupy_state.json").write_text("{}", encoding="utf-8")

    assert session.has_saved_session("gupy") is True


# ---- fakes for the Playwright-driving functions (open_context, login_interactively) ----


class FakePage:
    def goto(self, url):
        pass


class FakeContext:
    def __init__(self):
        self.init_scripts: list[str] = []
        self.closed = False
        self.storage_state_paths: list[str] = []

    def add_init_script(self, script):
        self.init_scripts.append(script)

    def new_page(self):
        return FakePage()

    def close(self):
        self.closed = True

    def storage_state(self, path):
        self.storage_state_paths.append(path)


class FakeBrowser:
    def __init__(self):
        self.closed = False
        self.contexts: list[FakeContext] = []

    def new_context(self, storage_state=None):
        ctx = FakeContext()
        self.contexts.append(ctx)
        return ctx

    def close(self):
        self.closed = True


class FailingBrowser(FakeBrowser):
    def new_context(self, storage_state=None):
        raise RuntimeError("boom")


class FakeChromium:
    def __init__(self, browser_factory=FakeBrowser):
        self._browser_factory = browser_factory
        self.launches: list[bool] = []
        self.browsers: list[FakeBrowser] = []

    def launch(self, headless):
        self.launches.append(headless)
        browser = self._browser_factory()
        self.browsers.append(browser)
        return browser


class FakePlaywright:
    def __init__(self, browser_factory=FakeBrowser):
        self.chromium = FakeChromium(browser_factory)
        self.stopped = False

    def start(self):
        return self

    def stop(self):
        self.stopped = True


def test_open_context_hides_webdriver_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SITES_STATE_DIR", tmp_path)
    fake_p = FakePlaywright()
    monkeypatch.setattr(session, "sync_playwright", lambda: fake_p)

    p, context = session.open_context("gupy", headless=True)

    assert session._HIDE_WEBDRIVER_FLAG in context.init_scripts
    assert fake_p.chromium.launches == [True]


def test_open_context_cleans_up_playwright_on_partial_failure(monkeypatch):
    fake_p = FakePlaywright(browser_factory=FailingBrowser)
    monkeypatch.setattr(session, "sync_playwright", lambda: fake_p)

    try:
        session.open_context("gupy", headless=True)
    except RuntimeError:
        pass

    assert fake_p.stopped is True  # not leaked even though context creation failed
    assert fake_p.chromium.browsers[0].closed is True


def test_login_interactively_saves_session_and_reports_success_without_verify_fn(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SITES_STATE_DIR", tmp_path)
    fake_p = FakePlaywright()
    monkeypatch.setattr(session, "sync_playwright", lambda: fake_p)

    enters = []
    result = session.login_interactively(
        "gupy", "https://login.example/signin", wait_for_enter=lambda prompt: enters.append(prompt)
    )

    assert result is True
    assert len(enters) == 1
    assert fake_p.chromium.browsers[0].contexts[0].storage_state_paths  # session was saved
    assert fake_p.stopped is True


def test_login_interactively_returns_false_and_still_saves_when_verification_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(config, "SITES_STATE_DIR", tmp_path)
    fake_p = FakePlaywright()
    monkeypatch.setattr(session, "sync_playwright", lambda: fake_p)

    result = session.login_interactively(
        "gupy",
        "https://login.example/signin",
        wait_for_enter=lambda prompt: None,
        verify_fn=lambda context: False,
    )

    assert result is False
    assert fake_p.chromium.browsers[0].contexts[0].storage_state_paths  # still saved -- real progress kept
    assert "não parece autenticada" in capsys.readouterr().out


def test_login_interactively_reports_success_when_verify_fn_passes(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(config, "SITES_STATE_DIR", tmp_path)
    fake_p = FakePlaywright()
    monkeypatch.setattr(session, "sync_playwright", lambda: fake_p)

    result = session.login_interactively(
        "gupy",
        "https://login.example/signin",
        wait_for_enter=lambda prompt: None,
        verify_fn=lambda context: True,
    )

    assert result is True
    assert "Sessão salva" in capsys.readouterr().out
