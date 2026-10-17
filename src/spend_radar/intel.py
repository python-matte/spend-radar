"""Evidence collection: news, pricing and competitors, behind a provider interface.

FixtureProvider reads invented SAMPLE items from disk and is the default.
LiveProvider is opt-in. It reads Google News RSS and, if you give one, a public pricing page.
It follows robots.txt, sends an honest user agent, rate limits, caches for 24 hours, and never
goes behind a login or paywall. It keeps a headline, a link, a date and a short snippet. It
never keeps an article.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.robotparser import RobotFileParser

from . import core_logic as cl
from .core_logic import money
from .schemas import (
    Analysis,
    EvidenceItem,
    IntelBundle,
    ProviderResult,
    RawItem,
    Vendor,
)

USER_AGENT = (
    "spend-radar/0.1 (open-source procurement research tool; "
    "reads public headlines and public pricing pages only; honours robots.txt)"
)
ROBOTS_TOKEN = "spend-radar"
CACHE_TTL_SECONDS = 24 * 60 * 60
MIN_REQUEST_INTERVAL = 2.0
MAX_BYTES = 1_000_000
SNIPPET_CHARS = 200
MAX_NEWS_ITEMS = 8
MAX_PRICE_SNIPPETS = 5
LOGIN_HINTS = ("login", "signin", "sign-in", "subscribe", "paywall", "/auth")


def slugify(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def default_fixtures_dir() -> Path:
    env = os.environ.get("SPEND_RADAR_DATA_DIR")
    base = Path(env) if env else Path(__file__).resolve().parents[2] / "data"
    return base / "intel_fixtures"


# Provider interface ----------------------------------------------------------------------


class NewsProvider(ABC):
    name: str

    @abstractmethod
    def fetch(self, vendor: str, pricing_url: str | None = None) -> ProviderResult:
        """Return raw items for one vendor. Must not raise for ordinary failures."""


class FixtureProvider(NewsProvider):
    name = "fixture"

    def __init__(self, fixtures_dir: Path | None = None) -> None:
        self.dir = fixtures_dir or default_fixtures_dir()

    def fetch(self, vendor: str, pricing_url: str | None = None) -> ProviderResult:
        path = self.dir / f"{slugify(vendor)}.json"
        if not path.exists():
            return ProviderResult(notes=[f"No fixture file for {vendor} ({path.name})."])
        doc = json.loads(path.read_text(encoding="utf-8"))
        items = [RawItem.model_validate(i) for i in doc.get("items", [])]
        notes = [doc.get("label", "Fixture data.")]
        if pricing_url:
            notes.append("A pricing URL was given but the fixture provider never fetches pages.")
        return ProviderResult(
            items=items, notes=notes, fiscal_year_end_month=doc.get("fiscal_year_end_month")
        )


# Disk cache ------------------------------------------------------------------------------


class DiskCache:
    """Small JSON cache on disk. Entries expire after ttl seconds."""

    def __init__(
        self,
        directory: Path,
        ttl: float = CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.dir = directory
        self.ttl = ttl
        self.clock = clock

    def _path(self, key: str) -> Path:
        return self.dir / (hashlib.sha256(key.encode()).hexdigest()[:40] + ".json")

    def get(self, key: str) -> object | None:
        path = self._path(key)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if self.clock() - float(doc.get("stored_at", 0)) > self.ttl:
            return None
        return doc.get("value")

    def set(self, key: str, value: object) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        doc = {"stored_at": self.clock(), "key": key, "value": value}
        self._path(key).write_text(json.dumps(doc), encoding="utf-8")


# HTTP ------------------------------------------------------------------------------------


class FetchError(Exception):
    """The network failed."""


class FetchBlocked(Exception):
    """We chose not to fetch: robots.txt, login or paywall."""


@dataclass
class HttpResponse:
    status: int
    body: str
    url: str


class HttpClient(ABC):
    @abstractmethod
    def get(self, url: str, user_agent: str, timeout: float = 10.0) -> HttpResponse: ...


class UrllibClient(HttpClient):
    def get(self, url: str, user_agent: str, timeout: float = 10.0) -> HttpResponse:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                raw = resp.read(MAX_BYTES)
                return HttpResponse(resp.status, raw.decode("utf-8", "replace"), resp.geturl())
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, "", url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise FetchError(str(exc)) from exc


class PoliteFetcher:
    """Wraps an HttpClient with robots.txt, rate limiting and paywall checks."""

    def __init__(
        self,
        client: HttpClient,
        cache: DiskCache,
        user_agent: str = USER_AGENT,
        min_interval: float = MIN_REQUEST_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.cache = cache
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.clock = clock
        self.sleep = sleep
        self._last: float | None = None
        self._robots: dict[str, RobotFileParser] = {}

    def _wait_turn(self) -> None:
        if self._last is not None:
            wait = self.min_interval - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._last = self.clock()

    def _raw_get(self, url: str) -> HttpResponse:
        self._wait_turn()
        return self.client.get(url, self.user_agent)

    def _robots_for(self, url: str) -> RobotFileParser:
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        parser = RobotFileParser()
        cached = self.cache.get(f"robots:{origin}")
        if isinstance(cached, str):
            parser.parse(cached.splitlines())
        else:
            resp = self._raw_get(origin + "/robots.txt")
            if resp.status in (404, 410):
                parser.parse([])
            elif resp.status == 200:
                self.cache.set(f"robots:{origin}", resp.body)
                parser.parse(resp.body.splitlines())
            else:
                # Cannot read the rules, so assume the answer is no.
                parser.parse(["User-agent: *", "Disallow: /"])
        self._robots[origin] = parser
        return parser

    def get_text(self, url: str) -> str:
        if not self._robots_for(url).can_fetch(ROBOTS_TOKEN, url):
            raise FetchBlocked(f"robots.txt does not allow {url}")
        resp = self._raw_get(url)
        if resp.status in (401, 402, 403):
            raise FetchBlocked(f"{url} needs a login or payment (HTTP {resp.status})")
        final = resp.url.lower()
        if any(hint in final for hint in LOGIN_HINTS):
            raise FetchBlocked(f"{url} redirected to a login or paywall page")
        if resp.status != 200:
            raise FetchError(f"HTTP {resp.status} from {url}")
        return resp.body


# Parsing ---------------------------------------------------------------------------------

_KIND_WORDS = [
    ("layoffs", ("layoff", "laid off", "job cuts", "cuts staff", "cut staff", "redundan")),
    ("acquisition", ("acquire", "acquisition", "merger", "buyout", "takeover")),
    ("funding", ("funding", "raises", "raised", "series ", "investment round")),
    ("security", ("breach", "security incident", "vulnerab", "hack", "ransomware")),
    ("outage", ("outage", "downtime", "went down", "disruption")),
    ("earnings", ("earnings", "revenue", "quarter", "guidance", "forecast")),
    ("leadership", ("ceo", "chief executive", "appoints", "steps down", "names new")),
    ("pricing_change", ("price increase", "raises prices", "pricing change", "new pricing")),
    ("product", ("launch", "unveil", "releases", "introduces", "new feature")),
]


def classify_kind(text: str) -> str:
    lowered = text.lower()
    for kind, words in _KIND_WORDS:
        if any(w in lowered for w in words):
            return kind
    return "general"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in ("p", "li", "div", "br", "tr", "h1", "h2", "h3", "td"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def strip_html(text: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(text)
    return re.sub(r"\s+", " ", " ".join(extractor.parts)).strip()


def shorten(text: str, limit: int = SNIPPET_CHARS) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "..."


def parse_news_rss(xml_text: str, today: date, limit: int = MAX_NEWS_ITEMS) -> list[RawItem]:
    if "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        raise FetchError("RSS feed contains a DOCTYPE or ENTITY declaration, refusing to parse")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FetchError(f"RSS feed is not valid XML: {exc}") from exc
    items: list[RawItem] = []
    for node in root.iter("item"):
        title = shorten(strip_html(node.findtext("title") or ""), 160)
        link = (node.findtext("link") or "").strip()
        if not title or not link:
            continue
        published = today
        raw_date = node.findtext("pubDate")
        if raw_date:
            try:
                published = parsedate_to_datetime(raw_date).date()
            except (TypeError, ValueError):
                published = today
        source = (node.findtext("source") or "").strip()
        snippet = shorten(strip_html(node.findtext("description") or ""))
        if not snippet or snippet.lower().startswith(title.lower()[:40]):
            snippet = f"Headline from {source}." if source else "Headline only."
        items.append(
            RawItem(
                bucket="situation",
                kind=classify_kind(title),
                title=title,
                url=link,
                date=published,
                snippet=snippet,
                source_type="news headline",
            )
        )
        if len(items) >= limit:
            break
    return items


_PRICE_RE = re.compile(r"[$€£]\s?\d")


def parse_pricing_page(html_text: str, url: str, today: date) -> list[RawItem]:
    extractor = _TextExtractor()
    extractor.feed(html_text)
    title = shorten(re.sub(r"\s+", " ", extractor.title).strip() or url, 120)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in "".join(extractor.parts).split("\n")]
    found: list[RawItem] = []
    for line in lines:
        if line and _PRICE_RE.search(line):
            found.append(
                RawItem(
                    bucket="pricing",
                    kind="list_price",
                    title=title,
                    url=url,
                    date=today,
                    snippet=shorten(line),
                    source_type="pricing page",
                )
            )
        if len(found) >= MAX_PRICE_SNIPPETS:
            break
    return found


# Live provider ---------------------------------------------------------------------------


def news_url(vendor: str) -> str:
    query = urllib.parse.quote_plus(f'"{vendor}"')
    return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


class LiveProvider(NewsProvider):
    name = "live"

    def __init__(
        self,
        fetcher: PoliteFetcher,
        cache: DiskCache,
        fallback: NewsProvider | None = None,
        today: date | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.cache = cache
        self.fallback = fallback
        self.today = today or date.today()

    def _cached_items(
        self, key: str, load: Callable[[], list[RawItem]], notes: list[str]
    ) -> list[RawItem]:
        cached = self.cache.get(key)
        if isinstance(cached, list):
            notes.append(f"Used cached result for {key.split(':', 1)[0]} (under 24 hours old).")
            return [RawItem.model_validate(i) for i in cached]
        items = load()
        self.cache.set(key, [i.model_dump(mode="json") for i in items])
        return items

    def fetch(self, vendor: str, pricing_url: str | None = None) -> ProviderResult:
        notes: list[str] = []
        items: list[RawItem] = []

        url = news_url(vendor)
        try:
            items += self._cached_items(
                f"news:{url}",
                lambda: parse_news_rss(self.fetcher.get_text(url), self.today),
                notes,
            )
        except (FetchBlocked, FetchError) as exc:
            notes.append(f"News not collected: {exc}")

        if pricing_url:
            try:
                items += self._cached_items(
                    f"pricing:{pricing_url}",
                    lambda: parse_pricing_page(
                        self.fetcher.get_text(pricing_url), pricing_url, self.today
                    ),
                    notes,
                )
                if not any(i.bucket == "pricing" for i in items):
                    notes.append("No price found on the pricing page. Unknown, ask for a quote.")
            except (FetchBlocked, FetchError) as exc:
                notes.append(f"Pricing page not collected: {exc}")

        notes.append(
            "Live mode does not search for competitors. The competitors bucket is empty "
            "unless fixtures fill it."
        )
        if not items and self.fallback is not None:
            fallback = self.fallback.fetch(vendor, pricing_url)
            fallback.notes = [
                *notes,
                "Live collection returned nothing, so the fixture provider was used.",
                *fallback.notes,
            ]
            return fallback
        return ProviderResult(items=items, notes=notes)


def build_live_provider(
    cache_dir: Path | None = None, fallback: NewsProvider | None = None
) -> LiveProvider:
    directory = cache_dir or Path(os.environ.get("SPEND_RADAR_CACHE_DIR", ".spend_radar_cache"))
    cache = DiskCache(directory)
    fetcher = PoliteFetcher(UrllibClient(), cache)
    return LiveProvider(fetcher, cache, fallback=fallback)


# Our own data as evidence -----------------------------------------------------------------


def our_position_items(
    vendor: Vendor, vendors: list[Vendor], analysis: Analysis
) -> list[EvidenceItem]:
    """Sentences about our own contract, usage and spend. These are the 'our data' evidence."""
    as_of = analysis.as_of
    info = next(r for r in analysis.renewals if r.vendor == vendor.vendor)
    unused = next(u for u in analysis.unused if u.vendor == vendor.vendor)
    share = cl.share_of_spend_pct(vendor, vendors)
    slug = vendor.slug

    sentences: list[tuple[str, str]] = []
    sentences.append(
        (
            "Spend and share of total",
            f"{vendor.vendor} costs {money(vendor.annual_cost)} a year on a "
            f"{vendor.pricing_model.value} plan. That is {share:.1f}% of our total software "
            f"spend of {money(analysis.total_spend)}.",
        )
    )
    usage_text = (
        f"We bought {vendor.seats_purchased} seats and {vendor.seats_active_90d} were active in "
        f"the last 90 days, which is {unused.usage_pct:.0f}% in use."
    )
    if unused.applicable and unused.excess_seats > 0:
        usage_text += (
            f" We could drop {unused.excess_seats} seats and still keep "
            f"{cl.SEAT_HEADROOM_PCT}% headroom. The seat saving is between {money(unused.low)} "
            f"and {money(unused.high)} a year."
        )
    elif not unused.applicable:
        usage_text += f" The plan is {vendor.pricing_model.value}, so dropping seats would not "
        usage_text += "lower the bill."
    sentences.append(("Seat usage", usage_text))

    if info.days_to_deadline >= 0:
        timing = f"which is {info.days_to_deadline} days away"
    else:
        timing = f"which passed {-info.days_to_deadline} days ago"
    sentences.append(
        (
            "Renewal and notice deadline",
            f"The contract renews on {info.renewal_date.isoformat()}. The notice deadline is "
            f"{info.notice_deadline.isoformat()}, {timing}. The term is {vendor.term_months} "
            f"months and notice is {vendor.notice_days} days. Status: {info.status.value}.",
        )
    )
    if not vendor.auto_renew:
        auto = "Auto-renew is off."
    elif vendor.auto_renew_approved_by:
        auto = f"Auto-renew is on, with an exception approved by {vendor.auto_renew_approved_by}."
    else:
        auto = "Auto-renew is on and no exception is approved."
    sentences.append(("Auto-renew policy", auto))
    sentences.append(("Last uplift", f"The last renewal uplift was {vendor.last_uplift_pct:g}%."))

    group = next(
        (g for g in analysis.overlaps if any(m.vendor == vendor.vendor for m in g.members)), None
    )
    if group:
        me = next(m for m in group.members if m.vendor == vendor.vendor)
        others = [m for m in group.members if m.vendor != vendor.vendor]
        names = ", ".join(f"{m.vendor} at {money(m.cost_per_seat)} per seat a year" for m in others)
        noun = "tool" if len(others) == 1 else "tools"
        text = f"We also pay for {len(others)} other {group.category} {noun}: {names}."
        if group.target_vendor == vendor.vendor:
            text += (
                f" {vendor.vendor} is the cheapest of them at {money(me.cost_per_seat)} per seat "
                "a year, so the others could move here."
            )
        else:
            text += (
                f" Moving this vendor's {me.seats_active} active seats to {group.target_vendor} "
                f"at {money(group.target_cost_per_seat)} per seat a year could save between "
                f"{money(me.saving_if_moved * cl.LOW_RECOVERY)} and "
                f"{money(me.saving_if_moved * cl.HIGH_RECOVERY)} a year."
            )
        sentences.append(("Overlap in our portfolio", text))

    return [
        EvidenceItem(
            id=f"{slug}-our-{n}",
            vendor=vendor.vendor,
            bucket="our_position",
            origin="our_data",
            kind="our_data",
            title=title,
            url="data/vendors.csv",
            date=as_of,
            snippet=text,
            source_type="our own data",
        )
        for n, (title, text) in enumerate(sentences, start=1)
    ]


_PREFIX = {"situation": "sit", "pricing": "prc", "competitors": "cmp"}


def collect_intel(
    vendor: Vendor,
    vendors: list[Vendor],
    analysis: Analysis,
    provider: NewsProvider,
    pricing_url: str | None = None,
) -> IntelBundle:
    result = provider.fetch(vendor.vendor, pricing_url)
    origin = "live" if provider.name == "live" else "fixture"
    # A live provider that fell back reports fixture items. Mark them as such.
    if provider.name == "live" and any("fixture provider was used" in n for n in result.notes):
        origin = "fixture"

    raw = list(result.items)
    if result.fiscal_year_end_month:
        end = cl.next_fiscal_quarter_end(analysis.as_of, result.fiscal_year_end_month)
        month_name = calendar.month_name[result.fiscal_year_end_month]
        sample = "SAMPLE: " if origin == "fixture" else ""
        raw.append(
            RawItem(
                bucket="situation",
                kind="fiscal_timing",
                title=("[SAMPLE] " if sample else "") + "Fiscal quarter-end timing",
                url=f"https://example.com/sample/{vendor.slug}/fiscal" if sample else "n/a",
                date=analysis.as_of,
                snippet=(
                    f"{sample}The fiscal year ends in {month_name}. The next fiscal quarter ends "
                    f"on {end.isoformat()}, which is {(end - analysis.as_of).days} days away."
                ),
                source_type="vendor fiscal calendar",
            )
        )

    items: list[EvidenceItem] = []
    for bucket, prefix in _PREFIX.items():
        in_bucket = sorted(
            (r for r in raw if r.bucket == bucket), key=lambda r: r.date, reverse=True
        )
        for n, r in enumerate(in_bucket, start=1):
            items.append(
                EvidenceItem(
                    id=f"{vendor.slug}-{prefix}-{n}",
                    vendor=vendor.vendor,
                    origin=origin,  # type: ignore[arg-type]
                    **r.model_dump(),
                )
            )
    items += our_position_items(vendor, vendors, analysis)
    return IntelBundle(
        vendor=vendor.vendor,
        provider=provider.name,
        as_of=analysis.as_of,
        items=items,
        notes=result.notes,
    )


def render_intel_markdown(bundle: IntelBundle) -> str:
    def block(items: list[EvidenceItem], empty: str) -> list[str]:
        if not items:
            return [empty, ""]
        lines: list[str] = []
        for i in items:
            lines.append(f"- `{i.id}` {i.date.isoformat()}, {i.source_type}: **{i.title}**")
            lines.append(f"  {i.snippet}")
            lines.append(f"  Source: {i.url}")
        lines.append("")
        return lines

    out = [f"# Intel: {bundle.vendor}", ""]
    out.append(f"Provider: {bundle.provider}. As of {bundle.as_of.isoformat()}.")
    for note in bundle.notes:
        out.append(f"> {note}")
    out.append("")
    out += ["## Vendor situation", ""]
    out += block(bundle.bucket("situation"), "Nothing found in the sources checked.")
    out += ["## Pricing", ""]
    out += block(bundle.bucket("pricing"), "Unknown, ask for a quote.")
    out += ["## Competitors", ""]
    out += block(bundle.bucket("competitors"), "Nothing found in the sources checked.")
    out += ["## Our position (our own data)", ""]
    out += block(bundle.bucket("our_position"), "No data.")
    return "\n".join(out).rstrip() + "\n"
