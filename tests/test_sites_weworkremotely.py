import xml.etree.ElementTree as ET

import pytest

from jarvis.sites.base import SessionStatus, UpdatePlan
from jarvis.sites.weworkremotely import (
    WeWorkRemotelyAdapter,
    _fetch_items,
    _item_to_job_listing,
)

REAL_SHAPED_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>Postscript: Director, Email Deliverability</title>
  <region>Anywhere in the World</region>
  <category>Full-Stack Programming</category>
  <description>&lt;p&gt;&lt;strong&gt;Headquarters:&lt;/strong&gt; Remote&lt;/p&gt;&lt;p&gt;We need a data analyst.&lt;/p&gt;</description>
  <link>https://weworkremotely.com/remote-jobs/postscript-director-email-deliverability</link>
  <guid>https://weworkremotely.com/remote-jobs/postscript-director-email-deliverability</guid>
</item>
<item>
  <title>Clari + Salesloft: Senior Director, Product &amp; Strategy</title>
  <region>Anywhere in the World</region>
  <description>&lt;p&gt;Real work.&lt;/p&gt;</description>
  <link>https://weworkremotely.com/remote-jobs/clari-senior-director</link>
</item>
<item>
  <title>No colon here at all</title>
  <region></region>
  <description></description>
  <link>https://weworkremotely.com/remote-jobs/no-colon</link>
</item>
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


def _real_items() -> list[ET.Element]:
    root = ET.fromstring(REAL_SHAPED_FEED)
    return list(root.iter("item"))


def test_item_to_job_listing_splits_company_from_title_on_the_first_colon():
    listing = _item_to_job_listing(_real_items()[0])

    assert listing.company == "Postscript"
    assert listing.title == "Director, Email Deliverability"
    assert listing.site_name == "weworkremotely"
    assert listing.external_id == listing.url
    assert listing.location == "Remote (Anywhere in the World)"
    assert "data analyst" in listing.snippet.lower()
    assert "<p>" not in listing.snippet  # HTML stripped


def test_item_to_job_listing_splits_on_first_colon_even_when_company_name_has_one():
    # Real, confirmed-live case: the company name itself contains a
    # colon-adjacent "+" -- must still split correctly on the FIRST
    # ": " in the raw title.
    listing = _item_to_job_listing(_real_items()[1])

    assert listing.company == "Clari + Salesloft"
    assert listing.title == "Senior Director, Product & Strategy"


def test_item_to_job_listing_no_colon_keeps_the_whole_title_company_none():
    listing = _item_to_job_listing(_real_items()[2])

    assert listing.company is None
    assert listing.title == "No colon here at all"


def test_item_to_job_listing_location_defaults_to_bare_remote_when_region_missing():
    listing = _item_to_job_listing(_real_items()[2])

    assert listing.location == "Remote"


def test_item_to_job_listing_none_when_title_or_link_missing():
    root = ET.fromstring(
        "<item><title></title><link>https://x</link></item>"
    )
    assert _item_to_job_listing(root) is None

    root2 = ET.fromstring("<item><title>Company: Title</title></item>")
    assert _item_to_job_listing(root2) is None


def test_fetch_items_parses_a_real_shaped_feed(monkeypatch):
    import jarvis.sites.weworkremotely as wwr

    def _fake(req, timeout=None):
        return FakeResponse(REAL_SHAPED_FEED.encode("utf-8"))

    monkeypatch.setattr(wwr.urllib.request, "urlopen", _fake)

    items = _fetch_items()

    assert len(items) == 3


def test_fetch_items_returns_empty_list_on_malformed_xml(monkeypatch):
    import jarvis.sites.weworkremotely as wwr

    def _fake(req, timeout=None):
        return FakeResponse(b"<not><valid xml")

    monkeypatch.setattr(wwr.urllib.request, "urlopen", _fake)

    assert _fetch_items() == []


def test_fetch_items_returns_empty_list_on_network_error(monkeypatch):
    import urllib.error

    import jarvis.sites.weworkremotely as wwr

    def _raise(req, timeout=None):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(wwr.urllib.request, "urlopen", _raise)

    assert _fetch_items() == []


def test_search_jobs_converts_the_real_shaped_feed(monkeypatch):
    import jarvis.sites.weworkremotely as wwr

    def _fake(req, timeout=None):
        return FakeResponse(REAL_SHAPED_FEED.encode("utf-8"))

    monkeypatch.setattr(wwr.urllib.request, "urlopen", _fake)

    listings = WeWorkRemotelyAdapter().search_jobs("Data Analyst")

    assert len(listings) == 3


def test_search_jobs_query_has_no_effect_on_what_is_fetched(monkeypatch):
    # Documented, accepted limitation (see module docstring) -- no
    # working category filter, so every query re-fetches the same feed.
    import jarvis.sites.weworkremotely as wwr

    calls = []

    def _fake(req, timeout=None):
        calls.append(req.full_url)
        return FakeResponse(REAL_SHAPED_FEED.encode("utf-8"))

    monkeypatch.setattr(wwr.urllib.request, "urlopen", _fake)

    WeWorkRemotelyAdapter().search_jobs("Python")
    WeWorkRemotelyAdapter().search_jobs("SQL")

    assert calls[0] == calls[1] == wwr._FEED_URL


def test_search_jobs_respects_max_results(monkeypatch):
    import jarvis.sites.weworkremotely as wwr

    def _fake(req, timeout=None):
        return FakeResponse(REAL_SHAPED_FEED.encode("utf-8"))

    monkeypatch.setattr(wwr.urllib.request, "urlopen", _fake)

    listings = WeWorkRemotelyAdapter().search_jobs("Data", max_results=2)

    assert len(listings) == 2


def test_check_session_always_authenticated_no_login_exists():
    assert WeWorkRemotelyAdapter().check_session() == SessionStatus.AUTHENTICATED


def test_profile_methods_raise_not_implemented():
    adapter = WeWorkRemotelyAdapter()

    with pytest.raises(NotImplementedError):
        adapter.inspect_current_profile()
    with pytest.raises(NotImplementedError):
        adapter.build_update_plan(resume=None, current=None)
    with pytest.raises(NotImplementedError):
        adapter.preview_changes(plan=UpdatePlan(site_name="weworkremotely"))
    with pytest.raises(NotImplementedError):
        adapter.apply_changes(plan=UpdatePlan(site_name="weworkremotely"), confirmed=True)
