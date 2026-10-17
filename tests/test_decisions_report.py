"""Decisions, the short report, the brief recommendation and the dashboard."""

from __future__ import annotations

from html.parser import HTMLParser

from spend_radar import core_logic as cl
from spend_radar.brief import build_brief
from spend_radar.dashboard import render_dashboard
from spend_radar.intel import FixtureProvider, collect_intel
from spend_radar.loader import find_vendor
from spend_radar.report import render_report
from spend_radar.schemas import Action, Urgency


def test_decide_now_is_exactly_the_three_contracts_inside_or_past_the_window(analysis):
    now = [d for d in analysis.decisions if d.urgency is Urgency.NOW]
    assert [d.vendor for d in now] == ["Taskwave", "Meetly", "Boardwick"]  # soonest first
    by = {d.vendor: d for d in now}
    assert by["Taskwave"].decide_by.isoformat() == "2026-10-21"
    assert by["Boardwick"].action is Action.ESCALATE_ROLLOVER


def test_small_savings_do_not_become_decisions(analysis):
    ledgerleaf = cl.decision_for(analysis, "Ledgerleaf")
    assert ledgerleaf.action is Action.WATCH  # one spare seat, approved auto-renew exception


def test_every_vendor_gets_one_decision_and_the_overview_names_the_first_move(vendors, analysis):
    assert sorted(d.vendor for d in analysis.decisions) == sorted(v.vendor for v in vendors)
    overview = cl.build_overview(vendors, analysis)
    assert overview.recommendation.startswith("Start with Taskwave.")
    assert overview.now_count == 3


def test_short_report_leads_with_the_recommendation_and_is_much_shorter(vendors, analysis):
    short = render_report(vendors, analysis)
    full = render_report(vendors, analysis, full=True)
    assert short.index("## At a glance") < short.index("## Decide now")
    assert "Recommendation: Start with Taskwave" in short.split("## Decide now")[0]
    assert "## Renewals" not in short
    assert "# Detail" in full and "## Renewals" in full and "## Unused seats" in full
    assert len(short.splitlines()) < len(full.splitlines()) / 2


def test_brief_opens_with_a_recommendation_before_section_one(vendors, analysis, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    vendor = find_vendor(vendors, "Meetly")
    bundle = collect_intel(vendor, vendors, analysis, FixtureProvider())
    text = build_brief(vendor, vendors, analysis, bundle).markdown
    assert text.index("## Recommendation") < text.index("## 1. Where we stand")
    assert "**Decide by:** 2026-10-31" in text


class _Tags(HTMLParser):
    """Collects tag names and the text of the first <title>, which is the page title."""

    def __init__(self):
        super().__init__()
        self.tags: list[str] = []
        self.title = ""
        self._reading = False
        self._done = False

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "title" and not self._done:
            self._reading = True

    def handle_data(self, data):
        if self._reading:
            self.title += data

    def handle_endtag(self, tag):
        if tag == "title" and self._reading:
            self._reading = False
            self._done = True


def test_dashboard_is_one_self_contained_page(vendors, analysis):
    page = render_dashboard(vendors, analysis)
    parsed = _Tags()
    parsed.feed(page)
    assert parsed.title == "Spend Radar Dashboard"
    assert "script" not in parsed.tags
    # The only URL allowed is the SVG namespace. No outside requests.
    urls = {u for u in page.replace('"', " ").split() if u.startswith(("http://", "https://"))}
    assert urls <= {"http://www.w3.org/2000/svg"}
    assert all(v.vendor in page for v in vendors)
    assert "SAMPLE DATA" in page
    assert "prefers-color-scheme: dark" in page
    assert "Table view" in page
    for label in ("Act now", "Window closed", "Upcoming", "Fine"):
        assert label in page  # status is never colour alone
