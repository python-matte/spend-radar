"""Negotiation brief builder and the verifier.

Sections 2 to 6 are lists of claims. Each claim names an evidence item and quotes it word for
word. The verifier checks that. A claim that fails is never kept quietly. It goes under the
"Unverified, check before using" heading with the reasons.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from . import core_logic as cl
from .schemas import (
    Analysis,
    BriefClaims,
    Claim,
    EvidenceItem,
    FlaggedClaim,
    IntelBundle,
    RenewalStatus,
    Vendor,
    VerificationResult,
)

DEFAULT_MODEL = "claude-sonnet-5-5"
MIN_QUOTE_CHARS = 10
SECTIONS = ("leverage", "alternatives", "asks", "do_not_reveal", "questions")
UNVERIFIED_HEADING = "Unverified, check before using"

# The verifier -----------------------------------------------------------------------------

_DATE_RE = re.compile(r"\d{4}-\d{2}(?:-\d{2})?")
_NUM_RE = re.compile(r"(?<![\w.])(\$)?(\d[\d,]*(?:\.\d+)?)(%)?")

# Numbers that are our own negotiating targets, not facts about anyone.
POLICY_TOKENS = {("%", format(Decimal(cl.UPLIFT_CAP_TARGET_PCT), "f"))}


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _norm_number(raw: str) -> str | None:
    try:
        return format(Decimal(raw.replace(",", "")).normalize(), "f")
    except InvalidOperation:
        return None


def extract_tokens(text: str) -> tuple[set[str], set[tuple[str, str]]]:
    """Dates (as written) and typed numbers: ('$', '20'), ('%', '9') or ('n', '200')."""
    dates = set(_DATE_RE.findall(text))
    rest = _DATE_RE.sub(" ", text)
    numbers: set[tuple[str, str]] = set()
    for dollar, digits, percent in _NUM_RE.findall(rest):
        value = _norm_number(digits.rstrip(","))
        if value is None:
            continue
        kind = "$" if dollar else "%" if percent else "n"
        numbers.add((kind, value))
    return dates, numbers


def _allowed_tokens(bundle: IntelBundle) -> tuple[set[str], set[tuple[str, str]]]:
    dates: set[str] = set()
    numbers: set[tuple[str, str]] = set(POLICY_TOKENS)
    for item in bundle.items:
        d, n = extract_tokens(item.text)
        dates |= d
        numbers |= n
        dates.add(item.date.isoformat())
    return dates, numbers


def _check_claim(
    claim: Claim,
    bundle: IntelBundle,
    allowed_dates: set[str],
    allowed_numbers: set[tuple[str, str]],
) -> list[str]:
    reasons: list[str] = []
    item = bundle.get(claim.evidence_id) if claim.evidence_id else None
    if not claim.evidence_id:
        reasons.append("no evidence_id given")
    elif item is None:
        reasons.append(f"evidence_id {claim.evidence_id!r} is not in the stored evidence")

    quote = _norm_space(claim.quote)
    if not quote:
        reasons.append("no quote given")
    elif len(quote) < MIN_QUOTE_CHARS:
        reasons.append(f"quote is too short to check ({len(quote)} characters)")
    elif item is not None and quote not in _norm_space(item.text):
        reasons.append(f"quote not found word for word in evidence item {item.id}")

    dates, numbers = extract_tokens(claim.text)
    plain_values = {value for _, value in allowed_numbers}
    for found in sorted(dates):
        if found not in allowed_dates:
            reasons.append(f"date {found} does not appear in our data or evidence")
    for kind, value in sorted(numbers):
        shown = {"$": f"${value}", "%": f"{value}%", "n": value}[kind]
        ok = value in plain_values if kind == "n" else (kind, value) in allowed_numbers
        if not ok:
            reasons.append(f"number {shown} does not appear in our data or evidence")
    return reasons


def verify_brief(claims: BriefClaims, bundle: IntelBundle) -> VerificationResult:
    """Keep claims that check out. Flag the rest with reasons. Nothing is dropped silently."""
    allowed_dates, allowed_numbers = _allowed_tokens(bundle)
    kept: dict[str, list[Claim]] = {name: [] for name in SECTIONS}
    flagged: list[FlaggedClaim] = []
    for section in SECTIONS:
        for claim in getattr(claims, section):
            reasons = _check_claim(claim, bundle, allowed_dates, allowed_numbers)
            if reasons:
                flagged.append(FlaggedClaim(section=section, claim=claim, reasons=reasons))
            else:
                kept[section].append(claim)
    return VerificationResult(verified=BriefClaims(**kept), flagged=flagged)


# Rule-based template ------------------------------------------------------------------------

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

_SITUATION_FRAMING = {
    "earnings": "Weaker results than planned can make a vendor keen to protect existing revenue.",
    "layoffs": "Staff cuts can mean pressure to keep revenue and a thinner account team.",
    "leadership": "A leadership change can open room to reset terms.",
    "acquisition": "A pending deal can change prices and terms, so lock in what we want now.",
    "funding": "New funding pushes a vendor to grow, which can make expansion terms attractive.",
    "outage": "A recent outage supports a request for service credits.",
    "security": "A recent security incident supports a request for stronger terms and credits.",
    "product": "A product change may add cost. Ask what is included in our price.",
    "pricing_change": "They have announced a price change, so ask to hold today's price.",
    "fiscal_timing": "A fiscal quarter-end gives them a reason to close before it.",
}
_SITUATION_WEIGHT = {
    "pricing_change": 78,
    "security": 74,
    "outage": 73,
    "earnings": 72,
    "layoffs": 68,
    "fiscal_timing": 66,
    "acquisition": 65,
    "leadership": 55,
    "product": 50,
    "funding": 40,
}


def _sentence(item: EvidenceItem, key: str | None = None) -> str:
    parts = [s for s in _SENTENCE_SPLIT.split(item.snippet.strip()) if s]
    chosen = parts[0] if parts else item.snippet
    if key:
        chosen = next((s for s in parts if key in s), chosen)
    return chosen.removeprefix("SAMPLE: ")


def _claim(text: str, item: EvidenceItem, key: str | None = None) -> Claim:
    if item.kind == "fiscal_timing" and key is None:
        key = "next fiscal quarter"
    return Claim(text=text, evidence_id=item.id, quote=_sentence(item, key))


def _our(bundle: IntelBundle, title: str) -> EvidenceItem | None:
    return next((i for i in bundle.bucket("our_position") if i.title == title), None)


def _of_kind(bundle: IntelBundle, bucket: str, *kinds: str) -> list[EvidenceItem]:
    items = [i for i in bundle.items if i.bucket == bucket and i.kind in kinds]
    return sorted(items, key=lambda i: i.date, reverse=True)


def _ranked(scored: list[tuple[int, Claim]], limit: int | None = None) -> list[Claim]:
    ordered = sorted(enumerate(scored), key=lambda p: (-p[1][0], p[0]))
    claims = [c for _, (_, c) in ordered]
    return claims[:limit] if limit else claims


def build_claims_from_rules(
    vendor: Vendor, vendors: list[Vendor], analysis: Analysis, bundle: IntelBundle
) -> BriefClaims:
    info = next(r for r in analysis.renewals if r.vendor == vendor.vendor)
    unused = next(u for u in analysis.unused if u.vendor == vendor.vendor)
    group = next(
        (g for g in analysis.overlaps if any(m.vendor == vendor.vendor for m in g.members)), None
    )
    spend = _our(bundle, "Spend and share of total")
    usage = _our(bundle, "Seat usage")
    renewal = _our(bundle, "Renewal and notice deadline")
    auto = _our(bundle, "Auto-renew policy")
    uplift = _our(bundle, "Last uplift")
    overlap = _our(bundle, "Overlap in our portfolio")
    assert spend and usage and renewal and auto and uplift  # always built from our own data

    # Section 2: leverage points ------------------------------------------------------------
    lev: list[tuple[int, Claim]] = []
    if overlap and group and group.target_vendor != vendor.vendor:
        mine = next(m for m in group.members if m.vendor == vendor.vendor)
        if mine.saving_if_moved > 0:
            lev.append(
                (
                    80,
                    _claim(
                        "We already pay for a cheaper tool in this category that could take "
                        "these seats.",
                        overlap,
                        "Moving this vendor's",
                    ),
                )
            )
    if unused.applicable and unused.excess_seats > 0:
        weight = 75 if unused.usage_pct < cl.LOW_USAGE_PCT else 55
        lev.append((weight, _claim("We pay for seats nobody uses.", usage, "We could drop")))
    if vendor.last_uplift_pct >= cl.HIGH_UPLIFT_PCT:
        lev.append(
            (62, _claim("The last uplift was large, which supports a hard cap now.", uplift))
        )
    if info.days_to_deadline >= 0 and vendor.auto_renew:
        lev.append(
            (
                58,
                _claim(
                    "We can still give notice before the deadline, so a walk-away stays possible.",
                    renewal,
                    "notice deadline",
                ),
            )
        )
    for item in _of_kind(bundle, "situation", *_SITUATION_FRAMING):
        lev.append(
            (_SITUATION_WEIGHT.get(item.kind, 50), _claim(_SITUATION_FRAMING[item.kind], item))
        )
    for item in _of_kind(bundle, "competitors", "promotion"):
        lev.append((70, _claim("A competitor has a switching offer open right now.", item)))
    for item in _of_kind(bundle, "pricing", "discount_tier"):
        lev.append((69, _claim("The vendor publishes discount tiers. Ask which applies.", item)))
    for item in _of_kind(bundle, "competitors", "pricing"):
        lev.append((60, _claim("A competitor publishes a price we can compare against.", item)))
    leverage = _ranked(lev, limit=8)

    # Section 3: alternatives and walk-away -------------------------------------------------
    alts: list[Claim] = []
    has_alternative = False
    if overlap and group and group.target_vendor != vendor.vendor:
        alts.append(
            _claim(
                f"In our own portfolio, {group.target_vendor} is a cheaper option in this "
                "category.",
                overlap,
                "Moving this vendor's",
            )
        )
        has_alternative = True
    elif overlap:
        alts.append(
            _claim(
                "We are the cheapest option in our own portfolio here, so no internal "
                "alternative exists.",
                overlap,
                "is the cheapest",
            )
        )
    for item in _of_kind(bundle, "competitors", "alternative", "promotion", "pricing")[:3]:
        alts.append(_claim("Outside option from public sources.", item))
        has_alternative = True

    if info.status is RenewalStatus.WINDOW_CLOSED and vendor.auto_renew:
        walk = (
            "A walk-away is not realistic this cycle. The notice deadline has passed, so the "
            "contract rolls over. Ask for a mid-term concession and diary the next deadline."
        )
    elif has_alternative and info.days_to_deadline >= 0:
        walk = (
            "A walk-away is realistic only if we start now. Treat it as real once we hold a "
            "written quote and a migration plan from the alternative."
        )
    elif has_alternative:
        walk = (
            "A walk-away is possible but weak. Get a written quote and a migration plan before "
            "we say so."
        )
    else:
        walk = "No walk-away is evidenced yet. Get two written quotes before the first call."
    alts.append(_claim(walk, renewal, "notice deadline"))

    # Section 4: asks -----------------------------------------------------------------------
    asks: list[tuple[int, Claim]] = []
    if info.status is RenewalStatus.WINDOW_CLOSED and vendor.auto_renew:
        asks.append(
            (
                101,
                _claim(
                    "Ask in writing to be released from the rollover, or for a mid-term "
                    "concession. The deadline has passed, so frame it as a request and offer "
                    "something in return.",
                    renewal,
                    "notice deadline",
                ),
            )
        )
    if vendor.auto_renew and not vendor.auto_renew_approved_by:
        asks.append(
            (
                100,
                _claim(
                    "Remove auto-renew. Renewal should need our written yes.",
                    auto,
                ),
            )
        )
    elif vendor.auto_renew:
        asks.append(
            (
                60,
                _claim(
                    "Keep the approved exception only with a written reminder from the vendor "
                    "well before the notice deadline.",
                    auto,
                ),
            )
        )
    else:
        asks.append((10, _claim("Keep auto-renew off.", auto)))

    price_change = _of_kind(bundle, "situation", "pricing_change")
    big_uplift = vendor.last_uplift_pct >= cl.HIGH_UPLIFT_PCT
    asks.append(
        (
            90 if big_uplift or price_change else 80,
            _claim(
                f"Cap any renewal uplift at {cl.UPLIFT_CAP_TARGET_PCT}% for the term.",
                price_change[0] if price_change else uplift,
            ),
        )
    )
    if unused.applicable and unused.excess_seats > 0:
        weight = 95 if unused.usage_pct < cl.LOW_USAGE_PCT else 85 if unused.usage_pct < 85 else 40
        asks.append(
            (
                weight,
                _claim(
                    "True down seats to real use, keeping some headroom.", usage, "We could drop"
                ),
            )
        )
    if vendor.pricing_model.value == "per_seat":
        weight = 75 if unused.usage_pct < 85 else 45
        asks.append(
            (
                weight,
                _claim(
                    "Add flexible seats: the right to add or remove seats during the term "
                    "without a penalty.",
                    usage,
                    "We bought",
                ),
            )
        )
    asks.append(
        (
            70,
            _claim(
                "Ask for a price on a one-year term and on a multi-year term. Take the longer "
                "term only if the discount is clear and seats can still go down.",
                renewal,
                "The term is",
            ),
        )
    )
    incidents = _of_kind(bundle, "situation", "outage", "security")
    asks.append(
        (
            78 if incidents else 35,
            _claim(
                "Ask for service credits tied to uptime, and credits for the recent incident."
                if incidents
                else "Ask for service credits tied to uptime.",
                incidents[0] if incidents else spend,
                None if incidents else "costs",
            ),
        )
    )
    asks.append(
        (
            82 if price_change else 50,
            _claim(
                "Ask for a price hold for the full term.",
                price_change[0] if price_change else uplift,
            ),
        )
    )
    asks.append(
        (
            40,
            _claim(
                "Co-term any add-ons or other products from this vendor to this renewal date.",
                renewal,
                "The contract renews",
            ),
        )
    )
    comp_prices = _of_kind(bundle, "competitors", "pricing")
    asks.append(
        (
            65 if comp_prices else 45,
            _claim(
                "Add a benchmarking clause: if public prices for the same service fall, we can "
                "re-open the price.",
                comp_prices[0] if comp_prices else spend,
                None if comp_prices else "costs",
            ),
        )
    )

    # Section 5: what not to reveal ---------------------------------------------------------
    hide: list[Claim] = [
        _claim(
            "Do not tell them how close our notice deadline is or that time is short.",
            renewal,
            "notice deadline",
        ),
        _claim(
            "Do not share our savings estimates or target price. Ask first, and let them quote.",
            usage if unused.applicable and unused.excess_seats > 0 else spend,
            "We could drop" if unused.applicable and unused.excess_seats > 0 else "costs",
        ),
        _claim(
            "Do not volunteer our active seat count until we choose to ask for a true-down.",
            usage,
            "We bought",
        ),
    ]
    if overlap and group and group.target_vendor != vendor.vendor:
        hide.append(
            _claim(
                "Do not name the cheaper tool we already pay for until we are ready to use it.",
                overlap,
                "Moving this vendor's",
            )
        )

    # Section 6: questions ------------------------------------------------------------------
    qs: list[tuple[int, Claim]] = []
    pricing_items = _of_kind(bundle, "pricing", "list_price", "price_change", "discount_tier")
    if pricing_items:
        qs.append(
            (
                90,
                _claim(
                    "Does the published price apply to us, and what discount applies at our "
                    "size? Please put it in writing.",
                    pricing_items[0],
                ),
            )
        )
    else:
        qs.append(
            (
                90,
                _claim(
                    "We found no public price. What is the list price for our plan, and what "
                    "discount applies at our size? Please put it in writing.",
                    spend,
                    "costs",
                ),
            )
        )
    qs.append(
        (
            88,
            _claim(
                "Can we remove auto-renew and replace it with a written reminder from you?",
                auto,
            ),
        )
    )
    question_text = {
        "pricing_change": "Will the announced price change apply to our renewal, and can you "
        "hold today's price?",
        "outage": "What changed after the outage, and what credits can you give us?",
        "security": "What changed after the incident, and what credits and terms can you give?",
        "acquisition": "Will our terms, support or price change after the deal closes?",
        "layoffs": "Will our account team or support level change?",
        "leadership": "Who owns our account after the leadership change?",
        "funding": "How will the new funding change what is included in our plan?",
        "product": "Is the new product or module included in our price?",
        "earnings": "What would you need from us to close this renewal early?",
        "fiscal_timing": "What do you need from us to close before your quarter ends?",
    }
    for item in _of_kind(bundle, "situation", *question_text):
        qs.append((_SITUATION_WEIGHT.get(item.kind, 50), _claim(question_text[item.kind], item)))
    questions = _ranked(qs, limit=6)

    return BriefClaims(
        leverage=leverage,
        alternatives=alts,
        asks=_ranked(asks),
        do_not_reveal=hide,
        questions=questions,
    )


# Optional model step ------------------------------------------------------------------------

SYSTEM_PROMPT = """You draft sections of a procurement negotiation brief.
You are given evidence items as JSON. Each has an id, a bucket, a date, a source_type,
a title and a snippet.
Return ONLY a JSON object with these keys: leverage, alternatives, asks, do_not_reveal,
questions.
Each key holds a list of claims. Each claim is {"text": ..., "evidence_id": ..., "quote": ...}.
Rules:
- evidence_id must be an id from the evidence given.
- quote must be copied word for word from that item's title or snippet. Do not change a word.
- Do not invent prices, dates, percentages or counts. Use only numbers that appear in the evidence.
- If a price is not in the evidence, say it is unknown and to ask for a quote.
- Rank each list from most to least useful. Plain words, short sentences, no em dashes.
- Items with origin "fixture" are invented SAMPLE data. Treat them as test data."""


class LLMDraftError(Exception):
    pass


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise LLMDraftError("the model did not return a JSON object")
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMDraftError(f"the model returned invalid JSON: {exc}") from exc


def draft_with_llm(
    vendor: Vendor, bundle: IntelBundle, model: str | None = None, client: object | None = None
) -> BriefClaims:
    model = model or os.environ.get("SPEND_RADAR_MODEL", DEFAULT_MODEL)
    if client is None:
        try:
            import anthropic
        except ImportError as exc:
            raise LLMDraftError("the anthropic package is not installed") from exc
        client = anthropic.Anthropic()
    evidence = [
        {
            "id": i.id,
            "bucket": i.bucket,
            "origin": i.origin,
            "date": i.date.isoformat(),
            "source_type": i.source_type,
            "title": i.title,
            "snippet": i.snippet,
        }
        for i in bundle.items
    ]
    user = json.dumps({"vendor": vendor.vendor, "evidence": evidence}, indent=2)
    try:
        response = client.messages.create(  # type: ignore[attr-defined]
            model=model,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as exc:  # network, auth and quota errors all land here
        raise LLMDraftError(f"the model call failed: {exc}") from exc
    text = "".join(
        getattr(block, "text", "")
        for block in response.content
        if getattr(block, "type", "") == "text"
    )
    try:
        return BriefClaims.model_validate(_extract_json(text))
    except ValueError as exc:
        if isinstance(exc, LLMDraftError):
            raise
        raise LLMDraftError(f"the model JSON had the wrong shape: {exc}") from exc


# Rendering ----------------------------------------------------------------------------------


@dataclass
class BriefResult:
    markdown: str
    verification: VerificationResult
    drafted_by: str
    notes: list[str] = field(default_factory=list)


def _evidence_line(bundle: IntelBundle, claim: Claim) -> str:
    item = bundle.get(claim.evidence_id)
    quote = _norm_space(claim.quote)
    if item is None:
        return f'   - Evidence `{claim.evidence_id}`: "{quote}"'
    return f'   - Evidence `{item.id}` ({item.date.isoformat()}, {item.source_type}): "{quote}"'


def _numbered(bundle: IntelBundle, claims: list[Claim], empty: str) -> list[str]:
    if not claims:
        return [empty, ""]
    out: list[str] = []
    for n, claim in enumerate(claims, start=1):
        out.append(f"{n}. {claim.text}")
        out.append(_evidence_line(bundle, claim))
    out.append("")
    return out


def render_where_we_stand(vendor: Vendor, analysis: Analysis, bundle: IntelBundle) -> list[str]:
    unused = next(u for u in analysis.unused if u.vendor == vendor.vendor)
    out: list[str] = []
    for item in bundle.bucket("our_position"):
        out.append(f"- **{item.title}.** {item.snippet}")
    if vendor.auto_renew and not vendor.auto_renew_approved_by:
        out.append(
            "- **Policy check.** Auto-renew is on with no approved exception. "
            "That breaks our policy and needs strict watching."
        )
    out += ["", "Saving estimates and the assumptions behind them:", ""]
    out.append(f"- Unused seats: {unused.assumption}")
    group = next(
        (g for g in analysis.overlaps if any(m.vendor == vendor.vendor for m in g.members)), None
    )
    if group:
        out.append(f"- Overlap: {group.assumption}")
    out.append("- These are estimates, not quotes. Nothing here is legal or financial advice.")
    out.append("")
    return out


def _timeline_lines(vendor: Vendor, analysis: Analysis) -> list[str]:
    out: list[str] = []
    for when, label in cl.negotiation_timeline(vendor, analysis.as_of):
        delta = (when - analysis.as_of).days
        marker = f"in {delta} days" if delta > 0 else "today" if delta == 0 else "passed"
        out.append(f"- **{when.isoformat()}** ({marker}): {label}")
    out.append("")
    return out


def render_brief(
    vendor: Vendor,
    analysis: Analysis,
    bundle: IntelBundle,
    verification: VerificationResult,
    drafted_by: str,
    notes: list[str],
) -> str:
    v = verification.verified
    sample = any(i.origin == "fixture" for i in bundle.items)
    out: list[str] = [f"# Negotiation brief: {vendor.vendor}", ""]
    out.append(f"As of {analysis.as_of.isoformat()}. Drafted by: {drafted_by}.")
    out.append("")
    if sample:
        out += [
            "> **SAMPLE DATA.** The vendor, the figures and every news item in this brief are "
            "invented for demonstration. Do not quote any of it in a real negotiation.",
            "",
        ]
    out.append(
        "> Every claim in sections 2 to 6 names an evidence item and quotes it. A claim whose "
        "quote or numbers could not be matched is listed at the end under "
        f'"{UNVERIFIED_HEADING}".'
    )
    for note in notes:
        out.append(f"> {note}")
    out.append("")

    out += ["## 1. Where we stand", ""] + render_where_we_stand(vendor, analysis, bundle)

    out += ["## 2. Leverage points, ranked", ""]
    out += _numbered(bundle, v.leverage, "No verified leverage points.")

    out += ["## 3. Our alternatives (BATNA) and a realistic walk-away", ""]
    out += _numbered(bundle, v.alternatives, "No verified alternatives.")
    out += ["Public prices we found:", ""]
    prices = bundle.bucket("pricing")
    if prices:
        out += [f"- `{i.id}` ({i.date.isoformat()}, {i.source_type}): {i.snippet}" for i in prices]
    else:
        out.append("- This vendor: unknown, ask for a quote.")
    comp_prices = [i for i in bundle.bucket("competitors") if i.kind == "pricing"]
    if comp_prices:
        out += [
            f"- `{i.id}` ({i.date.isoformat()}, {i.source_type}): {i.snippet}" for i in comp_prices
        ]
    else:
        out.append("- Competitors: unknown, ask for a quote.")
    out.append("")

    out += ["## 4. The asks, ranked", ""]
    out += [
        "Targets inside the asks, such as the uplift cap, are our own settings. They are not facts "
        "about the vendor.",
        "",
    ]
    out += _numbered(bundle, v.asks, "No verified asks.")
    out += ["## 5. What not to reveal", ""]
    out += _numbered(bundle, v.do_not_reveal, "Nothing verified.")
    out += ["## 6. Questions to ask the vendor", ""]
    out += _numbered(bundle, v.questions, "No verified questions.")

    out += ["## 7. Timeline", ""] + _timeline_lines(vendor, analysis)

    out += [f"## {UNVERIFIED_HEADING}", ""]
    if not verification.flagged:
        out += ["None. Every claim in sections 2 to 6 matched its evidence.", ""]
    else:
        out += [
            "These claims did not pass the check. Do not use them until you have checked them "
            "against the source.",
            "",
        ]
        for f in verification.flagged:
            out.append(f"- Section: {f.section}. Claim: {f.claim.text}")
            out.append(
                f"  - Cited: `{f.claim.evidence_id or 'none'}`. Quote: "
                f'"{_norm_space(f.claim.quote)}"'
            )
            for reason in f.reasons:
                out.append(f"  - Problem: {reason}")
        out.append("")

    cited = {c.evidence_id for name in SECTIONS for c in getattr(v, name)}
    out += ["## Evidence used", ""]
    for item in bundle.items:
        if item.id in cited:
            out.append(
                f"- `{item.id}` {item.date.isoformat()}, {item.source_type}: {item.title}. "
                f"{item.url}"
            )
    out.append("")
    return "\n".join(out).rstrip() + "\n"


def build_brief(
    vendor: Vendor,
    vendors: list[Vendor],
    analysis: Analysis,
    bundle: IntelBundle,
    use_llm: bool = True,
    client: object | None = None,
    model: str | None = None,
) -> BriefResult:
    notes: list[str] = []
    claims: BriefClaims | None = None
    drafted_by = "rule-based template"
    wants_llm = use_llm and (client is not None or bool(os.environ.get("ANTHROPIC_API_KEY")))
    if wants_llm:
        model_name = model or os.environ.get("SPEND_RADAR_MODEL", DEFAULT_MODEL)
        try:
            claims = draft_with_llm(vendor, bundle, model_name, client)
            drafted_by = f"model {model_name}, then checked by the verifier"
        except LLMDraftError as exc:
            notes.append(f"The model draft failed ({exc}). The rule-based template was used.")
    if claims is None:
        claims = build_claims_from_rules(vendor, vendors, analysis, bundle)
    verification = verify_brief(claims, bundle)
    markdown = render_brief(vendor, analysis, bundle, verification, drafted_by, notes)
    return BriefResult(markdown, verification, drafted_by, notes)


__all__ = [
    "BriefResult",
    "build_brief",
    "build_claims_from_rules",
    "draft_with_llm",
    "extract_tokens",
    "render_brief",
    "verify_brief",
]
