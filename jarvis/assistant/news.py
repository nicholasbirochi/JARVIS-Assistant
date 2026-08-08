"""Occasional daily news briefing -- spoken at most once per calendar day,
folded into the greeting by jarvis/assistant/briefing.py. No account, no
API key, no paid service: just G1's own public RSS feed
(https://g1.globo.com/rss/g1/), parsed with stdlib xml.etree.ElementTree
(RSS is just XML) -- no new dependency.

This is the one place in JARVIS that reaches the internet for something
other than the local Ollama server or a site adapter the user explicitly
triggered -- deliberately narrow in scope (public headlines only, nothing
about the user ever sent anywhere) and fails completely silently: no
internet, a slow/unreachable feed, or a parsing hiccup all just mean no
news today, never a blocked or broken greeting.
"""

from __future__ import annotations

import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

NEWS_FEED_URL = "https://g1.globo.com/rss/g1/"
_FETCH_TIMEOUT_SECONDS = 5


def _last_briefing_date_path():
    from jarvis.config import LOCAL_STATE_DIR  # live lookup -- monkeypatchable in tests

    return LOCAL_STATE_DIR / "last_news_briefing_date.txt"


def _today() -> str:
    return date.today().isoformat()


def already_briefed_today() -> bool:
    path = _last_briefing_date_path()
    return path.exists() and path.read_text(encoding="utf-8").strip() == _today()


def _mark_briefed_today() -> None:
    path = _last_briefing_date_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_today(), encoding="utf-8")


def fetch_headlines(limit: int = 3) -> list[str] | None:
    """Returns up to `limit` real headline titles, or None on any failure
    (no internet, feed unreachable, malformed XML, timeout) -- never
    raises, this is a best-effort extra, not a core feature."""
    try:
        req = urllib.request.Request(NEWS_FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        titles = [item.findtext("title") for item in root.iter("item")]
        titles = [t.strip() for t in titles if t and t.strip()]
        return titles[:limit] if titles else None
    except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError):
        return None


def build_news_briefing() -> str | None:
    """Returns a short spoken news snippet, at most once per calendar day
    -- None if already briefed today, or the feed couldn't be reached
    (and NOT marked as briefed in that case, so a later activation the
    same day gets a real retry instead of staying silent all day because
    of one transient failure)."""
    if already_briefed_today():
        return None

    headlines = fetch_headlines()
    if not headlines:
        return None

    _mark_briefed_today()
    if len(headlines) == 1:
        return f"Uma notícia de hoje: {headlines[0]}."
    return "Algumas notícias de hoje: " + "; ".join(headlines) + "."
