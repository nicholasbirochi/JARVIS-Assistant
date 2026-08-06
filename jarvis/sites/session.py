"""Persistent Playwright session, shared by every site adapter.

Login is always a manual, one-time step in a real, visible browser window --
this code never sees a password. Once the user finishes logging in
themselves, Playwright's `storage_state` (cookies/localStorage) is saved to
disk under SITES_STATE_DIR and reused on every later run, so login only
happens once per site (until the site's own session naturally expires).

State files are gitignored (data/sites/) -- they're live session credentials,
not résumé data.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import BrowserContext, sync_playwright


def state_path(site_name: str) -> Path:
    from jarvis.config import SITES_STATE_DIR  # live lookup -- monkeypatchable in tests

    return SITES_STATE_DIR / f"{site_name}_state.json"


def has_saved_session(site_name: str) -> bool:
    return state_path(site_name).exists()


def open_context(site_name: str, *, headless: bool) -> tuple[object, BrowserContext]:
    """Launches a browser and returns (playwright, context) with the site's
    saved session loaded, if one exists. Caller is responsible for closing
    both (see `closing_context`). `playwright` is returned (not just the
    context) because it must stay alive for as long as the browser does --
    letting it get garbage-collected while the context is still in use
    crashes the driver."""
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=headless)
    saved_state = state_path(site_name)
    context = browser.new_context(storage_state=str(saved_state) if saved_state.exists() else None)
    return p, context


def save_session(site_name: str, context: BrowserContext) -> None:
    from jarvis.config import SITES_STATE_DIR

    SITES_STATE_DIR.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(state_path(site_name)))


def login_interactively(site_name: str, login_url: str, *, wait_for_enter=input) -> None:
    """Opens a real, visible browser window at `login_url` and waits for the
    user to confirm (Enter) once they've finished logging in themselves --
    no fixed timeout, no guessing at a JS "is logged in" condition per site
    (fragile, and unverifiable without already having a live session).
    Saves the resulting session on success. Never headless -- a human has
    to be there to type their own credentials (and complete MFA/CAPTCHA if
    the site asks for it). `wait_for_enter` is swappable for tests."""
    p = sync_playwright().start()
    try:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(login_url)
        print(f"Faça login normalmente na janela que abriu ({login_url}).")
        wait_for_enter("Quando terminar de logar (perfil carregado), aperte Enter aqui... ")
        save_session(site_name, context)
        print(f"Sessão salva para {site_name!r}. Não vai precisar logar de novo.")
        browser.close()
    finally:
        p.stop()
