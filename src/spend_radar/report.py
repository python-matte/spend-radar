"""Portfolio report and the short text summary for `analyze`."""

from __future__ import annotations

from . import core_logic as cl
from .core_logic import money
from .schemas import Analysis, Decision, RenewalStatus, Urgency, Vendor


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


def _decision_table(decisions: list[Decision]) -> list[str]:
    rows = []
    for d in decisions:
        saving = _range(d.saving_low, d.saving_high) if d.saving_high > 0 else "no estimate"
        rows.append(
            [
                f"**{d.vendor}**",
                d.owner_team,
                d.action.value,
                d.decide_by.isoformat(),
                saving,
                d.headline,
            ]
        )
    return _table(["Vendor", "Team", "Action", "Decide by", "Saving a year", "What to do"], rows)


def render_report(
    vendors: list[Vendor], analysis: Analysis, sample: bool = True, full: bool = False
) -> str:
    by_name = {v.vendor: v for v in vendors}
    ov = cl.build_overview(vendors, analysis)
    todo = cl.actionable(analysis.decisions)
    now = [d for d in todo if d.urgency is Urgency.NOW]
    soon = [d for d in todo if d.urgency is Urgency.SOON]
    later = [d for d in todo if d.urgency is Urgency.LATER]

    out: list[str] = ["# Spend radar report", ""]
    out.append(f"As of {analysis.as_of.isoformat()}. {len(vendors)} vendors.")
    out.append("")
    if sample:
        out += [
            "> **SAMPLE DATA.** Every vendor, cost and date here is invented for demonstration.",
            "",
        ]

    out += ["## At a glance", ""]
    out += [f"**Recommendation: {ov.recommendation}**", ""]
    out += [
        f"- **Decide now:** {ov.now_count} contracts, with "
        f"{_range(ov.now_saving_low, ov.now_saving_high)} a year at stake. These are inside "
        "the notice window or already locked in.",
        f"- **Coming up:** {ov.soon_count} more decisions in the next 90 days. "
        f"{ov.later_count} later.",
        f"- **Spend:** {money(ov.total_spend)} a year. Rough recoverable range "
        f"{_range(ov.saving_low, ov.saving_high)}. Estimates, not promises.",
        f"- **Auto-renew:** {ov.auto_renew_no_exception} of {ov.auto_renew_total} auto-renew "
        "contracts have no approved exception. The goal is none.",
        "",
    ]

    out += ["## Decide now", ""]
    out += _decision_table(now) if now else ["Nothing is inside the notice window.", ""]

    out += ["## Coming up (next 90 days)", ""]
    out += _decision_table(soon) if soon else ["Nothing in the next 90 days.", ""]

    if later:
        names = ", ".join(d.vendor for d in later)
        out += [f"## Later ({len(later)})", "", f"{names}.", ""]

    out += ["## Auto-renew watchlist, soonest first", ""]
    watch = [
        (r, by_name[r.vendor])
        for r in sorted(analysis.renewals, key=lambda r: (r.notice_deadline, r.vendor))
        if by_name[r.vendor].auto_renew
    ]
    out += _table(
        ["Vendor", "Notice deadline", "Days", "Rolls over on", "Approved exception"],
        [
            [
                v.vendor,
                r.notice_deadline.isoformat(),
                _days(r.days_to_deadline),
                r.renewal_date.isoformat(),
                v.auto_renew_approved_by or "NONE",
            ]
            for r, v in watch[:5]
        ],
    )
    if len(watch) > 5:
        out += [f"{len(watch) - 5} more auto-renew contracts are in the full report.", ""]

    if not full:
        out += [
            "---",
            "",
            "More detail: `spend-radar report --full`. Charts: `spend-radar dashboard`. "
            "A brief for one vendor: `spend-radar brief <vendor>`.",
            "",
        ]
        return "\n".join(out).rstrip() + "\n"

    out += ["---", "", "# Detail", ""]
    out += ["## Auto-renew watchlist (all)", ""]
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
