"""Occasional daily news briefing -- spoken at most once per calendar day,
folded into the greeting by jarvis/assistant/briefing.py. No account, no
API key, no paid service: just two of Olhar Digital's own public RSS
category feeds (inteligência artificial, big data), parsed with stdlib
xml.etree.ElementTree (RSS is just XML) -- no new dependency.

Scoped to data/AI news specifically, not general headlines -- an earlier
version used G1's general front-page feed, which surfaced whatever was on
the news that day (crime, weather, politics...), not what Nicholas
actually wanted. Fixed two ways, deliberately redundant: (1) the feeds
themselves are topic-dedicated category feeds, not general ones, and (2)
every headline pulled from them is still re-checked against
_TOPIC_PATTERN before being spoken, as a safety net -- these feeds are
tag-based on the publisher's side and do occasionally drift (a
"dados"-tagged legal/privacy story with nothing to do with data science
showed up once while checking this), so "sempre sobre dados e IA" is
enforced here in code, not just trusted to the source.

This is one of the few places in JARVIS that reaches the internet for
something other than the local Ollama server or a site adapter the user
explicitly triggered -- deliberately narrow in scope (public headlines
only, nothing about the user ever sent anywhere) and fails completely
silently: no internet, a slow/unreachable feed, or a parsing hiccup all
just mean no news today, never a blocked or broken greeting.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

AI_FEED_URL = "https://olhardigital.com.br/editorias/inteligencia-artificial/feed/"
DATA_FEED_URL = "https://olhardigital.com.br/tag/big-data/feed/"
NEWS_FEED_URLS = [AI_FEED_URL, DATA_FEED_URL]
_FETCH_TIMEOUT_SECONDS = 5

# Safety net, not the primary filter (the feeds above are already topic
# feeds) -- re-checked per headline before speaking it. `\bIA\b` is safe
# case-insensitively despite how common "-ia" is as a word ending in
# Portuguese (família, polícia, ...): word boundaries require "ia" to be
# its own token, which that suffix never is.
_TOPIC_PATTERN = re.compile(
    r"\bIA\b"
    r"|intelig[êe]ncia artificial"
    r"|machine learning"
    r"|deep learning"
    r"|aprendizado de m[áa]quina"
    r"|rede neural"
    r"|chatgpt|openai|anthropic|claude|gemini|copilot|deepmind|nvidia"
    r"|\bllm\b"
    r"|modelo de linguagem"
    r"|algoritmo"
    r"|big data"
    r"|data science"
    r"|ci[êe]ncia de dados"
    r"|an[áa]lise de dados"
    r"|\bdados\b",
    re.IGNORECASE,
)


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


def _fetch_feed_titles(url: str) -> list[str]:
    """Returns every title from one feed, or [] on any failure (no
    internet, feed unreachable, malformed XML, timeout) -- never raises,
    and a single feed failing must never take the other one down with it."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        titles = [item.findtext("title") for item in root.iter("item")]
        return [t.strip() for t in titles if t and t.strip()]
    except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError):
        return []


def fetch_headlines(limit: int = 3) -> list[str] | None:
    """Pools titles from both feeds, keeps only ones matching
    _TOPIC_PATTERN, dedups, and returns up to `limit` -- or None if
    nothing on-topic came back from either feed."""
    seen: set[str] = set()
    on_topic: list[str] = []
    for url in NEWS_FEED_URLS:
        for title in _fetch_feed_titles(url):
            if title in seen or not _TOPIC_PATTERN.search(title):
                continue
            seen.add(title)
            on_topic.append(title)
    return on_topic[:limit] if on_topic else None


def build_news_briefing() -> str | None:
    """Returns a short spoken news snippet, at most once per calendar day
    -- None if already briefed today, or no on-topic headline could be
    found (and NOT marked as briefed in that case, so a later activation
    the same day gets a real retry instead of staying silent all day
    because of one transient failure)."""
    if already_briefed_today():
        return None

    headlines = fetch_headlines()
    if not headlines:
        return None

    _mark_briefed_today()
    if len(headlines) == 1:
        return f"Uma notícia de hoje sobre dados e IA: {headlines[0]}."
    return "Algumas notícias de hoje sobre dados e IA: " + "; ".join(headlines) + "."
