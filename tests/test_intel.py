from __future__ import annotations

from datetime import date

from spend_radar.intel import (
    USER_AGENT,
    DiskCache,
    FetchError,
    FixtureProvider,
    HttpClient,
    HttpResponse,
    LiveProvider,
    PoliteFetcher,
    collect_intel,
    parse_news_rss,
    render_intel_markdown,
)
from spend_radar.loader import find_vendor

TODAY = date(2026, 10, 17)

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Exampleco raises prices - Example News</title>
<link>https://example.com/a</link><pubDate>Mon, 12 Oct 2026 08:00:00 GMT</pubDate>
<description>&lt;a href="x"&gt;Exampleco raises prices&lt;/a&gt;
&lt;font&gt;Example News&lt;/font&gt;</description>
<source>Example News</source></item>
</channel></rss>"""


class FakeClient(HttpClient):
    def __init__(self, routes=None, error=None):
        self.routes = routes or {}
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def get(self, url, user_agent, timeout=10.0):
        self.calls.append((url, user_agent))
        if self.error:
            raise self.error
        for prefix, resp in self.routes.items():
            if url.startswith(prefix):
                return resp
        return HttpResponse(404, "", url)


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def make_live(tmp_path, client, clock=None, wall=None, fallback=None):
    clock = clock or Clock()
    cache = DiskCache(tmp_path / "cache", clock=wall or (lambda: 5000.0))
    fetcher = PoliteFetcher(client, cache, clock=clock, sleep=clock.sleep)
    return LiveProvider(fetcher, cache, fallback=fallback, today=TODAY), clock


ALLOW = {
    "https://news.google.com/robots.txt": HttpResponse(200, "User-agent: *\nAllow: /", "x"),
    "https://news.google.com/rss": HttpResponse(200, RSS, "https://news.google.com/rss"),
}


def test_all_fixtures_are_labelled_sample_and_use_example_urls(vendors):
    provider = FixtureProvider()
    for v in vendors:
        result = provider.fetch(v.vendor)
        assert result.items, v.vendor
        assert "SAMPLE" in result.notes[0]
        for item in result.items:
            assert item.url.startswith("https://example.com/")
            assert item.title.startswith("[SAMPLE]")


def test_missing_price_says_unknown_ask_for_a_quote(vendors, analysis):
    vendor = find_vendor(vendors, "Datanest")
    bundle = collect_intel(vendor, vendors, analysis, FixtureProvider())
    assert bundle.bucket("pricing") == []
    assert "Unknown, ask for a quote." in render_intel_markdown(bundle)


def test_live_provider_falls_back_to_fixtures_when_offline(tmp_path, vendors, analysis):
    live, _ = make_live(
        tmp_path, FakeClient(error=FetchError("offline")), fallback=FixtureProvider()
    )
    bundle = collect_intel(find_vendor(vendors, "Taskwave"), vendors, analysis, live)
    assert bundle.bucket("situation")
    assert all(i.origin in ("fixture", "our_data") for i in bundle.items)
    assert any("fixture provider was used" in n for n in bundle.notes)


def test_cache_is_used_for_24_hours_then_expires(tmp_path):
    wall = {"now": 5000.0}
    client = FakeClient(ALLOW)
    live, _ = make_live(tmp_path, client, wall=lambda: wall["now"])
    live.fetch("Exampleco")
    first = len(client.calls)
    live.fetch("Exampleco")
    assert len(client.calls) == first  # served from disk
    wall["now"] += 24 * 3600 + 1
    live.fetch("Exampleco")
    assert len(client.calls) > first


def test_robots_txt_disallow_blocks_the_fetch(tmp_path):
    routes = {
        "https://news.google.com/robots.txt": HttpResponse(200, "User-agent: *\nDisallow: /", "x"),
        "https://news.google.com/rss": HttpResponse(200, RSS, "x"),
    }
    client = FakeClient(routes)
    live, _ = make_live(tmp_path, client)
    result = live.fetch("Exampleco")
    assert result.items == []
    assert any("robots.txt" in n for n in result.notes)
    assert not any("/rss" in url for url, _ in client.calls)


def test_login_or_paywall_responses_are_skipped(tmp_path):
    routes = {**ALLOW, "https://news.google.com/rss": HttpResponse(403, "", "x")}
    live, _ = make_live(tmp_path, FakeClient(routes))
    result = live.fetch("Exampleco")
    assert result.items == []
    assert any("login or payment" in n for n in result.notes)


def test_requests_are_rate_limited_and_use_an_honest_user_agent(tmp_path):
    client = FakeClient(ALLOW)
    live, clock = make_live(tmp_path, client)
    live.fetch("Exampleco")
    assert clock.slept and clock.slept[0] > 0
    assert all(ua == USER_AGENT and "spend-radar" in ua for _, ua in client.calls)


def test_rss_keeps_only_headline_link_date_and_a_short_snippet():
    items = parse_news_rss(RSS, TODAY)
    assert len(items) == 1
    item = items[0]
    assert item.url == "https://example.com/a"
    assert item.date == date(2026, 10, 12)
    assert len(item.snippet) <= 203
    assert "<" not in item.snippet


def test_rss_with_entity_declarations_is_refused():
    bad = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><rss><channel/></rss>'
    try:
        parse_news_rss(bad, TODAY)
    except FetchError:
        return
    raise AssertionError("expected FetchError")
