"""All the math. Pure functions: no I/O, no network, no LLM.

Every function takes the as-of date as an argument, so results are the same every run.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta

from .schemas import (
    Action,
    Analysis,
    Change,
    Decision,
    OverlapGroup,
    OverlapMember,
    Overview,
    PriorityItem,
    RenewalInfo,
    RenewalStatus,
    Snapshot,
    SnapshotEntry,
    UnusedSeatSaving,
    Urgency,
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
    renewals = [renewal_info(v, as_of) for v in vendors]
    return Analysis(
        as_of=as_of,
        total_spend=total_spend(vendors),
        renewals=renewals,
        unused=unused,
        overlaps=overlaps,
        priorities=priority_ranking(vendors, as_of, unused, overlaps),
        vendor_saving_low=low,
        vendor_saving_high=high,
        decisions=decide(vendors, renewals, unused, overlaps, low, high),
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


# 5. Decisions ------------------------------------------------------------------------------

RIGHT_SIZE_BELOW_PCT = 85  # below this usage, trimming seats is worth a decision
MIN_DECISION_SAVING = 1500  # a seat or overlap decision needs a high case at least this big


def decide(
    vendors: list[Vendor],
    renewals: list[RenewalInfo],
    unused: list[UnusedSeatSaving],
    overlaps: list[OverlapGroup],
    low: dict[str, float],
    high: dict[str, float],
) -> list[Decision]:
    """One recommended decision per vendor. Most urgent first, then biggest saving."""
    info_by = {r.vendor: r for r in renewals}
    unused_by = {u.vendor: u for u in unused}
    overlap_by: dict[str, tuple[OverlapGroup, OverlapMember]] = {}
    for group in overlaps:
        for m in group.members:
            overlap_by[m.vendor] = (group, m)

    decisions: list[Decision] = []
    for v in vendors:
        info = info_by[v.vendor]
        seats = unused_by[v.vendor]
        pair = overlap_by.get(v.vendor)
        can_consolidate = bool(pair and pair[1].saving_if_moved >= MIN_DECISION_SAVING)
        can_trim = (
            seats.applicable
            and seats.high >= MIN_DECISION_SAVING
            and seats.usage_pct < RIGHT_SIZE_BELOW_PCT
        )
        no_exception = v.auto_renew and not v.auto_renew_approved_by
        due = info.notice_deadline if v.auto_renew else info.renewal_date
        due_days = info.days_to_deadline if v.auto_renew else info.days_to_renewal

        if can_consolidate:
            assert pair is not None
            driver = f"{pair[0].target_vendor} is a cheaper option for these seats."
        elif can_trim:
            driver = f"{seats.excess_seats} seats are unused."
        elif no_exception:
            driver = "Remove auto-renew."
        else:
            driver = ""

        if info.status is RenewalStatus.WINDOW_CLOSED:
            action = Action.ESCALATE_ROLLOVER
            due = info.renewal_date
            headline = (
                "Ask in writing to be released from the rollover on "
                f"{info.renewal_date.isoformat()}. "
                f"The notice deadline passed {-info.days_to_deadline} days ago."
            )
        elif info.status is RenewalStatus.ACT_NOW:
            action = Action.NEGOTIATE_NOW
            if v.auto_renew:
                headline = (
                    f"Negotiate or give notice by {due.isoformat()} ({due_days} days). {driver}"
                )
            else:
                headline = (
                    f"Renews in {due_days} days. Decide whether to renew, and on what "
                    f"terms. {driver}"
                )
        elif can_consolidate:
            assert pair is not None
            action = Action.CONSOLIDATE
            headline = (
                f"Plan a move of {pair[1].seats_active} seats to {pair[0].target_vendor}, or use "
                f"that option to cut the price. Decide by {due.isoformat()}."
            )
        elif can_trim:
            action = Action.RIGHT_SIZE
            headline = (
                f"Cut {seats.excess_seats} unused seats at renewal. Only {seats.usage_pct:.0f}% "
                f"of seats are in use. Decide by {due.isoformat()}."
            )
        elif v.last_uplift_pct >= HIGH_UPLIFT_PCT:
            action = Action.CAP_UPLIFT
            headline = (
                f"Cap the uplift. The last one was {v.last_uplift_pct:g}%. "
                f"Decide by {due.isoformat()}."
            )
        elif no_exception:
            action = Action.REMOVE_AUTO_RENEW
            headline = f"Ask to remove auto-renew. Decide by {due.isoformat()}."
        else:
            action = Action.WATCH
            headline = "No action needed this month."

        if info.status in (RenewalStatus.WINDOW_CLOSED, RenewalStatus.ACT_NOW):
            urgency = Urgency.NOW
        elif info.status is RenewalStatus.UPCOMING:
            urgency = Urgency.SOON
        else:
            urgency = Urgency.LATER
        if action is Action.WATCH:
            urgency = Urgency.LATER

        decisions.append(
            Decision(
                vendor=v.vendor,
                owner_team=v.owner_team,
                action=action,
                urgency=urgency,
                status=info.status,
                headline=headline.strip(),
                decide_by=due,
                start_by=info.start_negotiating_by,
                annual_cost=v.annual_cost,
                saving_low=low[v.vendor] if action is not Action.WATCH else 0.0,
                saving_high=high[v.vendor] if action is not Action.WATCH else 0.0,
                auto_renew_no_exception=bool(no_exception),
            )
        )

    rank = {Urgency.NOW: 0, Urgency.SOON: 1, Urgency.LATER: 2}

    def sort_key(d: Decision) -> tuple:
        mid = (d.saving_low + d.saving_high) / 2
        watch = d.action is Action.WATCH
        if d.urgency is Urgency.NOW:
            return (rank[d.urgency], watch, d.decide_by, d.vendor)
        return (rank[d.urgency], watch, -mid, d.vendor)

    return sorted(decisions, key=sort_key)


def decision_for(analysis: Analysis, vendor_name: str) -> Decision:
    return next(d for d in analysis.decisions if d.vendor == vendor_name)


def actionable(decisions: list[Decision]) -> list[Decision]:
    return [d for d in decisions if d.action is not Action.WATCH]


def build_overview(vendors: list[Vendor], analysis: Analysis) -> Overview:
    todo = actionable(analysis.decisions)
    now = [d for d in todo if d.urgency is Urgency.NOW]
    soon = [d for d in todo if d.urgency is Urgency.SOON]
    later = [d for d in todo if d.urgency is Urgency.LATER]
    if now:
        names = [d.vendor for d in now]
        first = now[0]
        rest = f" Then {', '.join(names[1:])}." if len(names) > 1 else ""
        recommendation = (
            f"Start with {first.vendor}. {first.headline}{rest}"
            if len(names) > 1
            else f"Start with {first.vendor}. {first.headline}"
        )
    elif soon:
        recommendation = f"Nothing is urgent. Prepare {soon[0].vendor} next. {soon[0].headline}"
    else:
        recommendation = "Nothing needs a decision this month."
    return Overview(
        total_spend=analysis.total_spend,
        saving_low=sum(analysis.vendor_saving_low.values()),
        saving_high=sum(analysis.vendor_saving_high.values()),
        now_count=len(now),
        now_saving_low=sum(d.saving_low for d in now),
        now_saving_high=sum(d.saving_high for d in now),
        soon_count=len(soon),
        later_count=len(later),
        auto_renew_no_exception=sum(
            1 for v in vendors if v.auto_renew and not v.auto_renew_approved_by
        ),
        auto_renew_total=sum(1 for v in vendors if v.auto_renew),
        recommendation=recommendation,
    )


# 6. Month on month -----------------------------------------------------------------------


def make_snapshot(vendors: list[Vendor], analysis: Analysis) -> Snapshot:
    info = {r.vendor: r for r in analysis.renewals}
    dec = {d.vendor: d for d in analysis.decisions}
    entries = {}
    for v in vendors:
        entries[v.vendor] = SnapshotEntry(
            status=info[v.vendor].status,
            urgency=dec[v.vendor].urgency,
            action=dec[v.vendor].action,
            renewal_date=v.renewal_date,
            auto_renew=v.auto_renew,
            days_to_deadline=info[v.vendor].days_to_deadline,
            saving_mid=(
                analysis.vendor_saving_low[v.vendor] + analysis.vendor_saving_high[v.vendor]
            )
            / 2,
        )
    return Snapshot(as_of=analysis.as_of, total_spend=analysis.total_spend, vendors=entries)


_CHANGE_ORDER = {
    "window_closed": 0,
    "new_now": 1,
    "still_open": 2,
    "renewed": 3,
    "closer": 4,
    "cleared": 5,
    "new_vendor": 6,
    "removed": 7,
}


def diff_snapshots(prev: Snapshot | None, cur: Snapshot) -> list[Change]:
    """What changed since the last run. Empty on the first run."""
    if prev is None:
        return []
    out: list[Change] = []
    for name, now in cur.vendors.items():
        before = prev.vendors.get(name)
        if before is None:
            out.append(Change(vendor=name, kind="new_vendor", text="New in the vendor list."))
            continue
        if now.renewal_date > before.renewal_date:
            text = f"Renewed. The renewal date moved to {now.renewal_date.isoformat()}."
            if before.auto_renew and not now.auto_renew:
                text += " Auto-renew was removed."
            out.append(Change(vendor=name, kind="renewed", text=text))
        elif (
            now.status is RenewalStatus.WINDOW_CLOSED
            and before.status is not RenewalStatus.WINDOW_CLOSED
        ):
            out.append(
                Change(
                    vendor=name,
                    kind="window_closed",
                    text=(
                        "The notice window closed. The contract will roll over on "
                        f"{now.renewal_date.isoformat()} unless the vendor agrees otherwise."
                    ),
                )
            )
        elif now.urgency is Urgency.NOW and before.urgency is not Urgency.NOW:
            out.append(
                Change(
                    vendor=name,
                    kind="new_now",
                    text=(
                        f"Now due. Last month it was {before.status.value}. "
                        f"This month it is {now.status.value}."
                    ),
                )
            )
        elif (
            now.urgency is Urgency.NOW
            and before.urgency is Urgency.NOW
            and now.action is not Action.WATCH
        ):
            out.append(
                Change(
                    vendor=name,
                    kind="still_open",
                    text="Still open from last month. The deadline is closer.",
                )
            )
        elif now.status is not before.status:
            out.append(
                Change(
                    vendor=name,
                    kind="closer",
                    text=f"Moved from {before.status.value} to {now.status.value}.",
                )
            )
        elif now.action is Action.WATCH and before.action is not Action.WATCH:
            out.append(Change(vendor=name, kind="cleared", text="No longer needs action."))
    for name in prev.vendors:
        if name not in cur.vendors:
            out.append(Change(vendor=name, kind="removed", text="No longer in the vendor list."))
    return sorted(out, key=lambda ch: (_CHANGE_ORDER[ch.kind], ch.vendor))
