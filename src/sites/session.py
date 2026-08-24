"""Persistent Playwright session, shared by every site adapter.

Login is always a manual, one-time step in a real, visible browser window --
this code never sees a password. Once the user finishes logging in
themselves, Playwright's `storage_state` (cookies/localStorage) is saved to
disk under SITES_STATE_DIR and reused on every later run, so login only
happens once per site (until the site's own session naturally expires).

State files live under LOCAL_STATE_DIR (config.py), deliberately
OUTSIDE the project folder and outside git -- they're live session
credentials, not résumé data, and this whole project sits inside an
actively-synced OneDrive folder, which is not an acceptable place for them.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import BrowserContext, sync_playwright

# Playwright's automated browser self-reports navigator.webdriver=True by
# default -- a standard bot-detection signal some sites use to silently
# reject a login (no CAPTCHA, no error message, the form just reloads
# empty, observed live against Gupy's own login page). Hiding it here is
# about not being falsely flagged as a bot while automating the user's OWN
# account, the entire point of this feature -- not about attacking or
# scraping a third party.
_HIDE_WEBDRIVER_FLAG = "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"


def state_path(site_name: str) -> Path:
    from config import SITES_STATE_DIR  # live lookup -- monkeypatchable in tests

    return SITES_STATE_DIR / f"{site_name}_state.json"


def has_saved_session(site_name: str) -> bool:
    return state_path(site_name).exists()


def open_context(site_name: str, *, headless: bool) -> tuple[object, BrowserContext]:
    """Launches a browser and returns (playwright, context) with the site's
    saved session loaded, if one exists. Caller is responsible for closing
    both (see `closing_context`). `playwright` is returned (not just the
    context) because it must stay alive for as long as the browser does --
    letting it get garbage-collected while the context is still in use
    crashes the driver.

    For a headed (headless=False) site (Catho, LinkedIn -- see their own
    module docstrings for why they need a real, non-headless window),
    callers should call minimize_window() right after creating their
    page, so it doesn't visibly interrupt Nicholas -- see that function's
    docstring for why this replaced an earlier, broken attempt at the
    same thing.

    Cleans up eagerly on a partial failure (browser launched but context
    creation fails, etc.) instead of leaking a Playwright/browser process
    that the caller never gets a handle to close."""
    p = sync_playwright().start()
    try:
        browser = p.chromium.launch(headless=headless)
        try:
            saved_state = state_path(site_name)
            context = browser.new_context(
                storage_state=str(saved_state) if saved_state.exists() else None
            )
            context.add_init_script(_HIDE_WEBDRIVER_FLAG)
        except Exception:
            browser.close()
            raise
    except Exception:
        p.stop()
        raise
    return p, context


def minimize_window(context: BrowserContext, page) -> None:
    """Minimizes the real OS-level window a headed (headless=False) page
    just opened in, via a raw CDP command -- so it doesn't visibly pop up
    over whatever Nicholas is doing, without giving up the real, headed
    browser fingerprint some sites require (Catho/LinkedIn 403 or behave
    differently when actually headless).

    2026-08-19: replaces an earlier attempt that launched the browser
    with `--window-position=-32000,-32000` -- confirmed live, on this
    machine, that Chromium silently ignores that flag: a window
    requested at (-32000,-32000) actually landed at (0,39), fully
    visible, exactly the problem Nicholas kept reporting. This CDP
    approach was verified differently and for real: queried
    `Browser.getWindowForTarget` again right after calling this, and its
    own `windowState` had genuinely flipped from "normal" to "minimized"
    -- not just "the command didn't error", an actual confirmed state
    change.

    Best-effort and silent on failure -- a future Chromium build
    changing this CDP behavior must never break the real page load this
    wraps; the worst case if it silently stops working is the old
    problem (a visible window), not a crash."""
    try:
        cdp = context.new_cdp_session(page)
        window_id = cdp.send("Browser.getWindowForTarget")["windowId"]
        cdp.send("Browser.setWindowBounds", {"windowId": window_id, "bounds": {"windowState": "minimized"}})
    except Exception:
        pass


def save_session(site_name: str, context: BrowserContext) -> None:
    from config import SITES_STATE_DIR

    SITES_STATE_DIR.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(state_path(site_name)))


def login_interactively(
    site_name: str, login_url: str, *, wait_for_enter=input, verify_fn=None
) -> bool:
    """Opens a real, visible browser window at `login_url` and waits for the
    user to confirm (Enter) once they've finished logging in themselves --
    no fixed timeout, no guessing at a JS "is logged in" condition per site
    (fragile, and unverifiable without already having a live session).
    Saves the resulting session either way. Never headless -- a human has
    to be there to type their own credentials (and complete MFA/CAPTCHA if
    the site asks for it). `wait_for_enter` is swappable for tests.

    `verify_fn(context) -> bool`, if given, is checked right after saving --
    found necessary in practice: a login can silently not actually finish
    (an OAuth popup that didn't fully redirect back, a form that got
    rejected without an error message) and pressing Enter anyway used to
    print an unconditional "session saved, all set" that wasn't true. The
    session is still saved either way -- real partial progress (e.g. an
    OAuth flow that did set some cookies) shouldn't be thrown away -- but
    the message now honestly reflects whether it actually worked. Returns
    the verification result (True if verify_fn wasn't given, since there's
    nothing to check)."""
    p = sync_playwright().start()
    try:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        context.add_init_script(_HIDE_WEBDRIVER_FLAG)
        page = context.new_page()
        page.goto(login_url)
        print(f"Faça login normalmente na janela que abriu ({login_url}).")
        wait_for_enter("Quando terminar de logar (perfil carregado), aperte Enter aqui... ")
        save_session(site_name, context)
        verified = verify_fn(context) if verify_fn is not None else True
        if verified:
            print(f"Sessão salva para {site_name!r}. Não vai precisar logar de novo.")
        else:
            print(
                f"Sessão salva, mas não parece autenticada de verdade -- o login pode não "
                f"ter concluído. Rode de novo se algo continuar pedindo login."
            )
        browser.close()
        return verified
    finally:
        p.stop()
