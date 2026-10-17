"""Portfolio report and the short text summary for `analyze`."""

from __future__ import annotations

from . import core_logic as cl
from .core_logic import money
from .schemas import Analysis, RenewalStatus, Vendor


def _range(low: float, high: float) -> str:
    return f"{money(round(low))} to {money(round(high))}"


def _days(days: int) -> str:
    return f"{days}" if days >= 0 else f"{-days} ago"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    out.append("")
    return out


def _counts(vendors: list[Vendor], analysis: Analysis) -> dict[str, int]:
    status = {r.vendor: r.status for r in analysis.renewals}
    return {
        "act_now": sum(1 for s in status.values() if s is RenewalStatus.ACT_NOW),
        "window_closed": sum(1 for s in status.values() if s is RenewalStatus.WINDOW_CLOSED),
        "low_usage": len(cl.low_usage_vendors(vendors)),
        "high_uplift": len(cl.high_uplift_vendors(vendors)),
        "overlap_groups": len(analysis.overlaps),
        "auto_no_exception": sum(
            1 for v in vendors if v.auto_renew and not v.auto_renew_approved_by
        ),
        "auto_total": sum(1 for v in vendors if v.auto_renew),
    }


def render_report(vendors: list[Vendor], analysis: Analysis, sample: bool = True) -> str:
    by_name = {v.vendor: v for v in vendors}
    counts = _counts(vendors, analysis)
    total_low = sum(analysis.vendor_saving_low.values())
    total_high = sum(analysis.vendor_saving_high.values())
    out: list[str] = ["# Spend radar report", ""]
    out.append(f"As of {analysis.as_of.isoformat()}. {len(vendors)} vendors.")
    out.append("")
    if sample:
        out += [
            "> **SAMPLE DATA.** Every vendor, cost and date here is invented for demonstration.",
            "",
        ]

    out += ["## Summary", ""]
    out += [
        f"- Total annual software spend: {money(analysis.total_spend)}.",
        f"- Estimated recoverable: {_range(total_low, total_high)} a year. This is a range "
        "built from stated assumptions. It is not a promise. Savings inside one category can "
        "overlap, so read the total as a rough upper sketch.",
        f"- Notice deadline in the next {cl.ACT_NOW_DAYS} days: {counts['act_now']}.",
        f"- Notice window already closed with auto-renew on: {counts['window_closed']}.",
        f"- Vendors under {cl.LOW_USAGE_PCT}% seat usage: {counts['low_usage']}.",
        f"- Vendors with a last uplift of {cl.HIGH_UPLIFT_PCT}% or more: {counts['high_uplift']}.",
        f"- Categories with more than one vendor: {counts['overlap_groups']}.",
        f"- Contracts on auto-renew: {counts['auto_total']}. "
        f"Of those, {counts['auto_no_exception']} have no approved exception.",
        "",
    ]

    out += ["## Auto-renew watchlist", ""]
    out += [
        "Our goal is no auto-renew on any contract. Each line below rolls over unless we act "
        "by the notice deadline. An approved exception is the rare case.",
        "",
    ]
    rows = []
    for r in sorted(analysis.renewals, key=lambda r: (r.notice_deadline, r.vendor)):
        v = by_name[r.vendor]
        if not v.auto_renew:
            continue
        exception = v.auto_renew_approved_by or "NONE"
        rows.append(
            [
                v.vendor,
                money(v.annual_cost),
                r.notice_deadline.isoformat(),
                _days(r.days_to_deadline),
                r.renewal_date.isoformat(),
                r.status.value,
                exception,
            ]
        )
    out += _table(
        [
            "Vendor",
            "Annual cost",
            "Notice deadline",
            "Days",
            "Rolls over on",
            "Status",
            "Approved exception",
        ],
        rows,
    )

    out += ["## Top 10 priorities", ""]
    out += [
        "Score is the middle of the saving range, times a status weight "
        f"(act now {cl.URGENCY_MULTIPLIER[RenewalStatus.ACT_NOW]}, window closed "
        f"{cl.URGENCY_MULTIPLIER[RenewalStatus.WINDOW_CLOSED]}, upcoming "
        f"{cl.URGENCY_MULTIPLIER[RenewalStatus.UPCOMING]}, fine "
        f"{cl.URGENCY_MULTIPLIER[RenewalStatus.FINE]}), times "
        f"{cl.AUTO_RENEW_NO_EXCEPTION_FACTOR} if auto-renew has no approved exception.",
        "",
    ]
    out += _table(
        ["Rank", "Vendor", "Status", "Saving range a year", "Score", "Why"],
        [
            [
                str(p.rank),
                p.vendor,
                p.status.value,
                _range(p.saving_low, p.saving_high),
                f"{p.score:,.0f}",
                p.why,
            ]
            for p in analysis.priorities
        ],
    )

    out += ["## Renewals", ""]
    out += [
        f"Status uses the notice deadline for auto-renew contracts (act now within "
        f"{cl.ACT_NOW_DAYS} days, upcoming within {cl.UPCOMING_DAYS}). Contracts without "
        "auto-renew use the renewal date. Start negotiating "
        f"{cl.NEGOTIATE_LEAD_DAYS} days before renewal.",
        "",
    ]
    out += _table(
        [
            "Vendor",
            "Renewal",
            "Notice deadline",
            "Days to deadline",
            "Start negotiating by",
            "Status",
        ],
        [
            [
                r.vendor,
                r.renewal_date.isoformat(),
                r.notice_deadline.isoformat(),
                _days(r.days_to_deadline),
                r.start_negotiating_by.isoformat(),
                r.status.value,
            ]
            for r in sorted(analysis.renewals, key=lambda r: (r.notice_deadline, r.vendor))
        ],
    )

    out += ["## Overlaps", ""]
    if not analysis.overlaps:
        out += ["No category has more than one vendor.", ""]
    for g in analysis.overlaps:
        out += [f"### {g.category}", ""]
        out += _table(
            ["Vendor", "Annual cost", "Active seats", "Cost per seat", "Saving if moved"],
            [
                [
                    m.vendor + (" (cheapest)" if m.vendor == g.target_vendor else ""),
                    money(m.annual_cost),
                    str(m.seats_active),
                    money(m.cost_per_seat),
                    money(m.saving_if_moved),
                ]
                for m in g.members
            ],
        )
        out += [
            f"Saving range: {_range(g.low, g.high)} a year.",
            "",
            f"Assumption: {g.assumption}",
            "",
        ]

    out += ["## Unused seats", ""]
    seat_rows = sorted(
        (u for u in analysis.unused if u.applicable and u.excess_seats > 0),
        key=lambda u: -u.high,
    )
    out += [
        f"Keep {cl.SEAT_HEADROOM_PCT}% headroom over active seats. Low case recovers "
        f"{cl.LOW_RECOVERY:.0%} of the gap, high case {cl.HIGH_RECOVERY:.0%}. Only per-seat "
        "plans are counted.",
        "",
    ]
    out += _table(
        ["Vendor", "Seats used", "Bought", "Excess seats", "Price per seat", "Saving range a year"],
        [
            [
                u.vendor,
                f"{u.usage_pct:.0f}%",
                str(by_name[u.vendor].seats_purchased),
                str(u.excess_seats),
                money(u.price_per_seat),
                _range(u.low, u.high),
            ]
            for u in seat_rows
        ],
    )
    out += [
        "Estimates only. They are not legal or financial advice. Check every figure against the "
        "contract before you quote it.",
        "",
    ]
    return "\n".join(out).rstrip() + "\n"


def render_analyze_text(vendors: list[Vendor], analysis: Analysis) -> str:
    counts = _counts(vendors, analysis)
    lines = [
        f"spend-radar analysis as of {analysis.as_of.isoformat()}",
        f"Vendors: {len(vendors)}. Total annual spend: {money(analysis.total_spend)}.",
        f"Notice deadline within {cl.ACT_NOW_DAYS} days: {counts['act_now']}.",
        f"Notice window closed with auto-renew on: {counts['window_closed']}.",
        f"Under {cl.LOW_USAGE_PCT}% seat usage: {counts['low_usage']}.",
        f"Last uplift {cl.HIGH_UPLIFT_PCT}% or more: {counts['high_uplift']}.",
        f"Categories with overlap: {counts['overlap_groups']}.",
        f"Auto-renew with no approved exception: {counts['auto_no_exception']}.",
        "",
        "Top priorities:",
    ]
    for p in analysis.priorities:
        lines.append(
            f"  {p.rank:>2}. {p.vendor:<12} {p.status.value:<14} "
            f"{_range(p.saving_low, p.saving_high):<22} {p.why}"
        )
    return "\n".join(lines) + "\n"
