import urllib.error

import pytest

import config
from assistant import news

AI_RSS = """<?xml version='1.0' encoding='UTF-8'?>
<rss version="2.0"><channel>
<title>IA</title>
<item><title>Nova IA da empresa X bate recorde de desempenho</title><link>https://x/a</link></item>
<item><title>ChatGPT ganha novidade nesta semana</title><link>https://x/b</link></item>
<item><title>Previsão do tempo para o fim de semana</title><link>https://x/c</link></item>
</channel></rss>""".encode("utf-8")

DATA_RSS = """<?xml version='1.0' encoding='UTF-8'?>
<rss version="2.0"><channel>
<title>Big Data</title>
<item><title>Como a análise de dados muda o mercado</title><link>https://y/a</link></item>
<item><title>Receita de bolo de cenoura para o fim de semana</title><link>https://y/b</link></item>
</channel></rss>""".encode("utf-8")


class FakeResponse:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _urlopen_by_url(mapping: dict[str, bytes]):
    def _fake(req, *a, **kw):
        return FakeResponse(mapping[req.full_url])

    return _fake


@pytest.fixture(autouse=True)
def _isolate_state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)


@pytest.fixture(autouse=True)
def _stub_both_feeds(monkeypatch):
    # Default: both feeds return their normal fixture content. Individual
    # tests override news.urllib.request.urlopen directly when they need
    # different behavior (errors, empty feeds, etc.).
    monkeypatch.setattr(
        news.urllib.request,
        "urlopen",
        _urlopen_by_url({news.AI_FEED_URL: AI_RSS, news.DATA_FEED_URL: DATA_RSS}),
    )


def test_already_briefed_today_false_when_no_file():
    assert news.already_briefed_today() is False


def test_already_briefed_today_true_after_marking():
    news.build_news_briefing()

    assert news.already_briefed_today() is True


def test_already_briefed_today_false_for_a_stale_date():
    path = news._last_briefing_date_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("2020-01-01", encoding="utf-8")

    assert news.already_briefed_today() is False


def test_fetch_headlines_only_keeps_on_topic_titles():
    result = news.fetch_headlines(limit=10)

    assert "Nova IA da empresa X bate recorde de desempenho" in result
    assert "ChatGPT ganha novidade nesta semana" in result
    assert "Como a análise de dados muda o mercado" in result
    assert "Previsão do tempo para o fim de semana" not in result
    assert "Receita de bolo de cenoura para o fim de semana" not in result


def test_fetch_headlines_respects_limit(monkeypatch):
    result = news.fetch_headlines(limit=2)

    assert len(result) == 2


def test_fetch_headlines_returns_none_when_nothing_on_topic(monkeypatch):
    off_topic_only = """<?xml version='1.0'?><rss><channel>
    <item><title>Previsão do tempo para o fim de semana</title></item>
    </channel></rss>""".encode("utf-8")
    monkeypatch.setattr(
        news.urllib.request,
        "urlopen",
        _urlopen_by_url({news.AI_FEED_URL: off_topic_only, news.DATA_FEED_URL: off_topic_only}),
    )

    assert news.fetch_headlines() is None


def test_fetch_headlines_survives_one_feed_failing(monkeypatch):
    def _fake(req, *a, **kw):
        if req.full_url == news.AI_FEED_URL:
            raise urllib.error.URLError("no internet")
        return FakeResponse(DATA_RSS)

    monkeypatch.setattr(news.urllib.request, "urlopen", _fake)

    result = news.fetch_headlines()

    assert result == ["Como a análise de dados muda o mercado"]


def test_fetch_headlines_returns_none_on_network_error(monkeypatch):
    def raise_it(*a, **kw):
        raise urllib.error.URLError("no internet")

    monkeypatch.setattr(news.urllib.request, "urlopen", raise_it)

    assert news.fetch_headlines() is None


def test_fetch_headlines_returns_none_on_malformed_xml(monkeypatch):
    monkeypatch.setattr(news.urllib.request, "urlopen", lambda *a, **kw: FakeResponse(b"not xml at all"))

    assert news.fetch_headlines() is None


def test_fetch_headlines_dedups_identical_titles_across_feeds(monkeypatch):
    same = b"""<?xml version='1.0'?><rss><channel>
    <item><title>ChatGPT ganha novidade nesta semana</title></item>
    </channel></rss>"""
    monkeypatch.setattr(
        news.urllib.request,
        "urlopen",
        _urlopen_by_url({news.AI_FEED_URL: same, news.DATA_FEED_URL: same}),
    )

    result = news.fetch_headlines()

    assert result == ["ChatGPT ganha novidade nesta semana"]


def test_build_news_briefing_returns_none_when_already_briefed_today(monkeypatch):
    news.build_news_briefing()  # first call: marks today as briefed
    calls = []
    monkeypatch.setattr(news.urllib.request, "urlopen", lambda *a, **kw: calls.append(1))

    result = news.build_news_briefing()

    assert result is None
    assert calls == []  # didn't even try fetching again


def test_build_news_briefing_does_not_mark_briefed_when_fetch_fails(monkeypatch):
    monkeypatch.setattr(
        news.urllib.request, "urlopen", lambda *a, **kw: (_ for _ in ()).throw(urllib.error.URLError("x"))
    )

    result = news.build_news_briefing()

    assert result is None
    assert news.already_briefed_today() is False  # so a later activation today can retry


def test_build_news_briefing_formats_multiple_headlines():
    result = news.build_news_briefing()

    assert result.startswith("Algumas notícias de hoje sobre dados e IA:")
    assert "Nova IA da empresa X bate recorde de desempenho" in result


def test_build_news_briefing_formats_single_headline(monkeypatch):
    single = b"""<?xml version='1.0'?><rss><channel>
    <item><title>ChatGPT ganha novidade nesta semana</title></item>
    </channel></rss>"""
    empty = b"""<?xml version='1.0'?><rss><channel></channel></rss>"""
    monkeypatch.setattr(
        news.urllib.request,
        "urlopen",
        _urlopen_by_url({news.AI_FEED_URL: single, news.DATA_FEED_URL: empty}),
    )

    result = news.build_news_briefing()

    assert result == "Uma notícia de hoje sobre dados e IA: ChatGPT ganha novidade nesta semana."
