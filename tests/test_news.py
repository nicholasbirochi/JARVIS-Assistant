import urllib.error

import pytest

from jarvis import config
from jarvis.assistant import news

SAMPLE_RSS = b"""<?xml version='1.0' encoding='UTF-8'?>
<rss version="2.0"><channel>
<title>g1</title>
<item><title>Primeira noticia do dia</title><link>https://g1.globo.com/a</link></item>
<item><title>Segunda noticia do dia</title><link>https://g1.globo.com/b</link></item>
<item><title>Terceira noticia do dia</title><link>https://g1.globo.com/c</link></item>
<item><title>Quarta noticia do dia</title><link>https://g1.globo.com/d</link></item>
</channel></rss>"""


class FakeResponse:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture(autouse=True)
def _isolate_state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)


def test_already_briefed_today_false_when_no_file():
    assert news.already_briefed_today() is False


def test_already_briefed_today_true_after_marking(monkeypatch):
    monkeypatch.setattr(news.urllib.request, "urlopen", lambda *a, **kw: FakeResponse(SAMPLE_RSS))

    news.build_news_briefing()

    assert news.already_briefed_today() is True


def test_already_briefed_today_false_for_a_stale_date():
    path = news._last_briefing_date_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("2020-01-01", encoding="utf-8")

    assert news.already_briefed_today() is False


def test_fetch_headlines_parses_titles_up_to_limit(monkeypatch):
    monkeypatch.setattr(news.urllib.request, "urlopen", lambda *a, **kw: FakeResponse(SAMPLE_RSS))

    result = news.fetch_headlines(limit=2)

    assert result == ["Primeira noticia do dia", "Segunda noticia do dia"]


def test_fetch_headlines_returns_none_on_network_error(monkeypatch):
    def raise_it(*a, **kw):
        raise urllib.error.URLError("no internet")

    monkeypatch.setattr(news.urllib.request, "urlopen", raise_it)

    assert news.fetch_headlines() is None


def test_fetch_headlines_returns_none_on_malformed_xml(monkeypatch):
    monkeypatch.setattr(news.urllib.request, "urlopen", lambda *a, **kw: FakeResponse(b"not xml at all"))

    assert news.fetch_headlines() is None


def test_build_news_briefing_returns_none_when_already_briefed_today(monkeypatch):
    monkeypatch.setattr(news.urllib.request, "urlopen", lambda *a, **kw: FakeResponse(SAMPLE_RSS))
    news.build_news_briefing()  # first call: marks today as briefed
    calls = []
    monkeypatch.setattr(news.urllib.request, "urlopen", lambda *a, **kw: calls.append(1) or FakeResponse(SAMPLE_RSS))

    result = news.build_news_briefing()

    assert result is None
    assert calls == []  # didn't even try fetching again


def test_build_news_briefing_does_not_mark_briefed_when_fetch_fails(monkeypatch):
    monkeypatch.setattr(news.urllib.request, "urlopen", lambda *a, **kw: (_ for _ in ()).throw(urllib.error.URLError("x")))

    result = news.build_news_briefing()

    assert result is None
    assert news.already_briefed_today() is False  # so a later activation today can retry


def test_build_news_briefing_formats_multiple_headlines(monkeypatch):
    monkeypatch.setattr(news.urllib.request, "urlopen", lambda *a, **kw: FakeResponse(SAMPLE_RSS))

    result = news.build_news_briefing()

    assert result.startswith("Algumas notícias de hoje:")
    assert "Primeira noticia do dia" in result


def test_build_news_briefing_formats_single_headline(monkeypatch):
    single = b"""<?xml version='1.0'?><rss><channel>
    <item><title>Unica noticia</title></item>
    </channel></rss>"""
    monkeypatch.setattr(news.urllib.request, "urlopen", lambda *a, **kw: FakeResponse(single))

    result = news.build_news_briefing()

    assert result == "Uma notícia de hoje: Unica noticia."
