"""All the math. Pure functions: no I/O, no network, no LLM.

Every function takes the as-of date as an argument, so results are the same every run.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta

from .schemas import (
    Analysis,
    OverlapGroup,
    OverlapMember,
    PriorityItem,
    RenewalInfo,
    RenewalStatus,
    UnusedSeatSaving,
    Vendor,
)

# Named settings. Change them here and every report follows.
SEAT_HEADROOM_PCT = 10  # keep this much headroom over active seats
LOW_RECOVERY = 0.5  # low case: half of the gap is recoverable
HIGH_RECOVERY = 1.0  # high case: all of the gap is recoverable
NEGOTIATE_LEAD_DAYS = 120  # start negotiating this long before renewal
ACT_NOW_DAYS = 30
UPCOMING_DAYS = 90
LOW_USAGE_PCT = 60  # below this seat usage a vendor is flagged
HIGH_UPLIFT_PCT = 8  # at or above this last uplift a vendor is flagged
URGENCY_MULTIPLIER = {
    RenewalStatus.ACT_NOW: 2.0,
    RenewalStatus.WINDOW_CLOSED: 1.5,  # locked in: escalate, do not ignore
    RenewalStatus.UPCOMING: 1.0,
    RenewalStatus.FINE: 0.5,
}
# Auto-renew with no approved exception breaks policy, so it ranks higher.
AUTO_RENEW_NO_EXCEPTION_FACTOR = 1.25
# Negotiating targets used by the brief. These are our asks, not facts.
UPLIFT_CAP_TARGET_PCT = 3


def money(value: float) -> str:
    if abs(value - round(value)) < 0.005:
        return f"${value:,.0f}"
    return f"${value:,.2f}"


def notice_deadline(renewal: date, notice_days: int) -> date:
    return renewal - timedelta(days=notice_days)


def start_negotiating_by(renewal: date) -> date:
    return renewal - timedelta(days=NEGOTIATE_LEAD_DAYS)


def add_months(d: date, months: int) -> date:
    index = d.year * 12 + (d.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def next_cycle_deadline(vendor: Vendor) -> date:
    """Notice deadline for the term after this one, if the contract rolls over."""
    next_renewal = add_months(vendor.renewal_date, vendor.term_months)
    return notice_deadline(next_renewal, vendor.notice_days)


def seat_usage_pct(vendor: Vendor) -> float:
    if vendor.seats_purchased == 0:
        return 0.0
    return 100.0 * vendor.seats_active_90d / vendor.seats_purchased


def cost_per_seat(vendor: Vendor) -> float:
    if vendor.seats_purchased == 0:
        return 0.0
    return vendor.annual_cost / vendor.seats_purchased


def total_spend(vendors: list[Vendor]) -> float:
    return sum(v.annual_cost for v in vendors)


def share_of_spend_pct(vendor: Vendor, vendors: list[Vendor]) -> float:
    total = total_spend(vendors)
    return 100.0 * vendor.annual_cost / total if total else 0.0


# 1. Renewals -----------------------------------------------------------------------------


def classify_status(vendor: Vendor, as_of: date) -> RenewalStatus:
    deadline = notice_deadline(vendor.renewal_date, vendor.notice_days)
    days_to_deadline = (deadline - as_of).days
    days_to_renewal = (vendor.renewal_date - as_of).days
    if vendor.auto_renew:
        if days_to_deadline < 0:
            return RenewalStatus.WINDOW_CLOSED
        days = days_to_deadline
    else:
        # Nothing rolls over by itself, so the renewal date is what matters.
        days = days_to_renewal
    if days <= ACT_NOW_DAYS:
        return RenewalStatus.ACT_NOW
    if days <= UPCOMING_DAYS:
        return RenewalStatus.UPCOMING
    return RenewalStatus.FINE


def renewal_info(vendor: Vendor, as_of: date) -> RenewalInfo:
    deadline = notice_deadline(vendor.renewal_date, vendor.notice_days)
    return RenewalInfo(
        vendor=vendor.vendor,
        renewal_date=vendor.renewal_date,
        notice_deadline=deadline,
        days_to_renewal=(vendor.renewal_date - as_of).days,
        days_to_deadline=(deadline - as_of).days,
        start_negotiating_by=start_negotiating_by(vendor.renewal_date),
        status=classify_status(vendor, as_of),
        auto_renew=vendor.auto_renew,
        auto_renew_approved_by=vendor.auto_renew_approved_by,
        next_cycle_deadline=next_cycle_deadline(vendor),
    )


# 3. Unused seats -------------------------------------------------------------------------


def unused_seat_saving(vendor: Vendor) -> UnusedSeatSaving:
    price = cost_per_seat(vendor)
    usage = seat_usage_pct(vendor)
    if vendor.pricing_model.value != "per_seat":
        return UnusedSeatSaving(
            vendor=vendor.vendor,
            applicable=False,
            usage_pct=usage,
            price_per_seat=price,
            assumption=(
                f"Pricing is {vendor.pricing_model.value}, so dropping seats would not lower "
                "the bill. No seat saving estimated."
            ),
        )
    # Integer maths, rounded up, so float noise never changes the seat count.
    keep = -(-vendor.seats_active_90d * (100 + SEAT_HEADROOM_PCT) // 100)
    excess = max(0, vendor.seats_purchased - keep)
    gap_value = excess * price
    return UnusedSeatSaving(
        vendor=vendor.vendor,
        applicable=True,
        usage_pct=usage,
        price_per_seat=price,
        excess_seats=excess,
        low=gap_value * LOW_RECOVERY,
        high=gap_value * HIGH_RECOVERY,
        assumption=(
            f"Keep {SEAT_HEADROOM_PCT}% headroom over active seats ({keep} seats). "
            f"The {excess} seats above that cost {money(price)} each per year. "
            f"Low case recovers {LOW_RECOVERY:.0%} of that gap, high case {HIGH_RECOVERY:.0%}."
        ),
    )


# 2. Overlaps -----------------------------------------------------------------------------


def find_overlaps(vendors: list[Vendor]) -> list[OverlapGroup]:
    groups: dict[str, list[Vendor]] = defaultdict(list)
    for v in vendors:
        groups[v.category.strip().lower()].append(v)

    result: list[OverlapGroup] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        target = min(members, key=lambda v: (cost_per_seat(v), v.vendor))
        target_rate = cost_per_seat(target)
        rows: list[OverlapMember] = []
        for v in sorted(members, key=lambda v: v.vendor):
            if v is target:
                saving = 0.0
            else:
                saving = max(0.0, v.annual_cost - v.seats_active_90d * target_rate)
            rows.append(
                OverlapMember(
                    vendor=v.vendor,
                    annual_cost=v.annual_cost,
                    seats_active=v.seats_active_90d,
                    cost_per_seat=cost_per_seat(v),
                    saving_if_moved=saving,
                )
            )
        gap = sum(r.saving_if_moved for r in rows)
        result.append(
            OverlapGroup(
                category=target.category,
                members=rows,
                target_vendor=target.vendor,
                target_cost_per_seat=target_rate,
                total_cost=sum(v.annual_cost for v in members),
                low=gap * LOW_RECOVERY,
                high=gap * HIGH_RECOVERY,
                assumption=(
                    f"Cost per seat is annual cost divided by seats purchased. {target.vendor} is "
                    f"cheapest at {money(target_rate)}. The estimate moves each other vendor's "
                    f"active seats onto {target.vendor} at that rate and drops the other "
                    f"contract. It assumes {target.vendor} will sell the extra seats at its "
                    f"current rate, which only a written quote can confirm. Low case counts "
                    f"{LOW_RECOVERY:.0%} of the gap (migration cost, rate changes), high case "
                    f"{HIGH_RECOVERY:.0%}."
                ),
            )
        )
    return sorted(result, key=lambda g: g.category)


# 4. Priority -----------------------------------------------------------------------------


def vendor_savings(
    vendors: list[Vendor],
    unused: list[UnusedSeatSaving],
    overlaps: list[OverlapGroup],
) -> tuple[dict[str, float], dict[str, float]]:
    """Low and high saving per vendor.

    A vendor can show up in both the seat gap and an overlap. The two describe the same
    money, so we take the larger of each bound, never the sum.
    """
    low = {v.vendor: 0.0 for v in vendors}
    high = {v.vendor: 0.0 for v in vendors}
    for u in unused:
        if u.applicable:
            low[u.vendor] = max(low[u.vendor], u.low)
            high[u.vendor] = max(high[u.vendor], u.high)
    for group in overlaps:
        for m in group.members:
            low[m.vendor] = max(low[m.vendor], m.saving_if_moved * LOW_RECOVERY)
            high[m.vendor] = max(high[m.vendor], m.saving_if_moved * HIGH_RECOVERY)
    return low, high


def _why(vendor: Vendor, info: RenewalInfo, unused: UnusedSeatSaving, ov_high: float) -> str:
    parts: list[str] = []
    if info.status is RenewalStatus.WINDOW_CLOSED:
        parts.append(
            f"notice deadline passed {-info.days_to_deadline} days ago, rolls over on "
            f"{info.renewal_date.isoformat()}"
        )
    elif vendor.auto_renew:
        parts.append(f"notice deadline in {info.days_to_deadline} days")
    else:
        parts.append(f"renews in {info.days_to_renewal} days, no auto-renew")
    if vendor.auto_renew and not vendor.auto_renew_approved_by:
        parts.append("auto-renew with no approved exception")
    if ov_high > 0 and ov_high >= unused.high:
        parts.append("overlaps with a cheaper tool")
    elif unused.applicable and unused.excess_seats > 0:
        parts.append(f"{unused.usage_pct:.0f}% of seats in use")
    return "; ".join(parts)


def priority_ranking(
    vendors: list[Vendor],
    as_of: date,
    unused: list[UnusedSeatSaving],
    overlaps: list[OverlapGroup],
    top_n: int = 10,
) -> list[PriorityItem]:
    low, high = vendor_savings(vendors, unused, overlaps)
    unused_by_name = {u.vendor: u for u in unused}
    overlap_high: dict[str, float] = defaultdict(float)
    for group in overlaps:
        for m in group.members:
            overlap_high[m.vendor] = max(overlap_high[m.vendor], m.saving_if_moved)

    scored: list[tuple[float, str, PriorityItem]] = []
    for v in vendors:
        mid = (low[v.vendor] + high[v.vendor]) / 2
        if mid <= 0:
            continue
        info = renewal_info(v, as_of)
        urgency = URGENCY_MULTIPLIER[info.status]
        policy = (
            AUTO_RENEW_NO_EXCEPTION_FACTOR if v.auto_renew and not v.auto_renew_approved_by else 1.0
        )
        item = PriorityItem(
            rank=0,
            vendor=v.vendor,
            status=info.status,
            saving_low=low[v.vendor],
            saving_high=high[v.vendor],
            saving_mid=mid,
            urgency_multiplier=urgency,
            auto_renew_factor=policy,
            score=mid * urgency * policy,
            why=_why(v, info, unused_by_name[v.vendor], overlap_high[v.vendor]),
        )
        scored.append((-item.score, v.vendor, item))
    scored.sort(key=lambda t: (t[0], t[1]))
    ranked = []
    for i, (_, _, item) in enumerate(scored[:top_n], start=1):
        ranked.append(item.model_copy(update={"rank": i}))
    return ranked


def analyze(vendors: list[Vendor], as_of: date) -> Analysis:
    unused = [unused_seat_saving(v) for v in vendors]
    overlaps = find_overlaps(vendors)
    low, high = vendor_savings(vendors, unused, overlaps)
    return Analysis(
        as_of=as_of,
        total_spend=total_spend(vendors),
        renewals=[renewal_info(v, as_of) for v in vendors],
        unused=unused,
        overlaps=overlaps,
        priorities=priority_ranking(vendors, as_of, unused, overlaps),
        vendor_saving_low=low,
        vendor_saving_high=high,
    )


# Helpers used by the planted-finding checks and the report ---------------------------------


def low_usage_vendors(vendors: list[Vendor]) -> list[Vendor]:
    return [v for v in vendors if seat_usage_pct(v) < LOW_USAGE_PCT]


def high_uplift_vendors(vendors: list[Vendor]) -> list[Vendor]:
    return [v for v in vendors if v.last_uplift_pct >= HIGH_UPLIFT_PCT]


def next_fiscal_quarter_end(as_of: date, fiscal_year_end_month: int) -> date:
    """First fiscal quarter end on or after as_of, for a year that ends in the given month."""
    quarter_months = {((fiscal_year_end_month - 1 + 3 * k) % 12) + 1 for k in range(4)}
    for offset in range(0, 13):
        index = as_of.year * 12 + (as_of.month - 1) + offset
        year, month0 = divmod(index, 12)
        month = month0 + 1
        if month in quarter_months:
            end = date(year, month, calendar.monthrange(year, month)[1])
            if end >= as_of:
                return end
    raise ValueError("unreachable: a quarter end always falls within 12 months")


def negotiation_timeline(vendor: Vendor, as_of: date) -> list[tuple[date, str]]:
    """Dated steps, working back from the notice deadline. Past dates are kept, not hidden."""
    renewal = vendor.renewal_date
    deadline = notice_deadline(renewal, vendor.notice_days)
    closed = classify_status(vendor, as_of) is RenewalStatus.WINDOW_CLOSED
    steps: list[tuple[date, str]] = [
        (
            start_negotiating_by(renewal),
            f"Start negotiating ({NEGOTIATE_LEAD_DAYS} days before renewal). Open talks.",
        ),
        (deadline - timedelta(days=45), "Written quotes from at least two alternatives in hand."),
        (deadline - timedelta(days=21), "Our position agreed inside: asks, walk-away, who signs."),
        (deadline - timedelta(days=7), "Written notice or signed amendment ready to send."),
    ]
    if closed:
        steps.append(
            (
                deadline,
                "Notice deadline. It has passed. Ask the vendor in writing for an exception or a "
                "mid-term change.",
            )
        )
        steps.append((renewal, "Contract rolls over for another term unless the vendor agrees."))
        steps.append(
            (
                next_cycle_deadline(vendor),
                "Next notice deadline if it rolls over. Put a reminder in the calendar now.",
            )
        )
    elif vendor.auto_renew:
        steps.append(
            (deadline, "Notice deadline. Send written notice or have the amendment signed.")
        )
        steps.append((renewal, "Renewal date. The contract rolls over if nothing was signed."))
    else:
        steps.append((deadline, "Date to confirm in writing whether we renew."))
        steps.append((renewal, "Renewal date. The contract ends if nothing was signed."))
    return sorted(steps, key=lambda s: s[0])
