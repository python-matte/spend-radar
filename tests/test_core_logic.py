from __future__ import annotations

from datetime import date

import pytest

from helpers import make_vendor
from spend_radar import core_logic as cl
from spend_radar.schemas import RenewalStatus

AS_OF = date(2026, 10, 17)


def test_notice_deadline_across_a_year_boundary():
    assert cl.notice_deadline(date(2027, 1, 15), 30) == date(2026, 12, 16)
    assert cl.notice_deadline(date(2027, 1, 10), 45) == date(2026, 11, 26)
    assert cl.notice_deadline(date(2028, 3, 1), 1) == date(2028, 2, 29)  # leap year


def test_add_months_clips_to_month_end_and_crosses_years():
    assert cl.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert cl.add_months(date(2026, 12, 20), 12) == date(2027, 12, 20)
    assert cl.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_start_negotiating_is_120_days_before_renewal():
    assert cl.start_negotiating_by(date(2027, 1, 15)) == date(2026, 9, 17)


@pytest.mark.parametrize(
    ("renewal", "expected"),
    [
        (date(2026, 10, 17), RenewalStatus.ACT_NOW),  # deadline today
        (date(2026, 11, 16), RenewalStatus.ACT_NOW),  # 30 days out
        (date(2026, 11, 17), RenewalStatus.UPCOMING),  # 31 days out
        (date(2027, 1, 15), RenewalStatus.UPCOMING),  # 90 days out
        (date(2027, 1, 16), RenewalStatus.FINE),  # 91 days out
        (date(2026, 10, 16), RenewalStatus.WINDOW_CLOSED),  # yesterday
    ],
)
def test_status_boundaries_for_auto_renew(renewal, expected):
    vendor = make_vendor(renewal_date=renewal, notice_days=0, auto_renew=True)
    assert cl.classify_status(vendor, AS_OF) is expected


def test_without_auto_renew_the_renewal_date_drives_status():
    vendor = make_vendor(renewal_date=date(2026, 12, 1), notice_days=90, auto_renew=False)
    assert cl.classify_status(vendor, AS_OF) is RenewalStatus.UPCOMING


def test_unused_seats_gives_a_range_never_one_number():
    # 200 bought, 170 active. Keep 10% headroom: 187 seats. Excess 13. Price 240 a seat.
    vendor = make_vendor(annual_cost=48000, seats_purchased=200, seats_active_90d=170)
    saving = cl.unused_seat_saving(vendor)
    assert saving.excess_seats == 13
    assert saving.high == pytest.approx(13 * 240)
    assert saving.low == pytest.approx(saving.high / 2)
    assert saving.low < saving.high
    assert "10% headroom" in saving.assumption


def test_unused_seats_not_estimated_for_flat_pricing():
    vendor = make_vendor(pricing_model="flat", seats_purchased=100, seats_active_90d=10)
    saving = cl.unused_seat_saving(vendor)
    assert saving.applicable is False
    assert saving.low == saving.high == 0


def test_overlap_saving_is_a_range_with_the_assumption_shown(analysis):
    group = next(g for g in analysis.overlaps if g.category == "project management")
    assert group.target_vendor == "Planhive"
    # Taskwave: 48,000 - 170 x 210 = 12,300. Boardwick: 26,400 - 100 x 210 = 5,400.
    assert group.high == pytest.approx(17700)
    assert group.low == pytest.approx(8850)
    assert "cheapest" in group.assumption
    assert "written quote" in group.assumption


def test_priority_is_ranked_and_capped_at_ten(analysis):
    scores = [p.score for p in analysis.priorities]
    assert len(analysis.priorities) == 10
    assert scores == sorted(scores, reverse=True)
    assert [p.rank for p in analysis.priorities] == list(range(1, 11))


def test_closed_window_is_not_marked_down_and_policy_breakers_rank_higher(analysis):
    boardwick = next(p for p in analysis.priorities if p.vendor == "Boardwick")
    assert boardwick.urgency_multiplier == cl.URGENCY_MULTIPLIER[RenewalStatus.WINDOW_CLOSED]
    assert boardwick.urgency_multiplier > cl.URGENCY_MULTIPLIER[RenewalStatus.UPCOMING]
    assert boardwick.auto_renew_factor == cl.AUTO_RENEW_NO_EXCEPTION_FACTOR


def test_approved_exception_does_not_get_the_policy_factor():
    plain = make_vendor(vendor="A", seats_active_90d=40)
    approved = make_vendor(
        vendor="B", seats_active_90d=40, auto_renew_approved_by="Head of Finance"
    )
    analysis = cl.analyze([plain, approved], AS_OF)
    factors = {p.vendor: p.auto_renew_factor for p in analysis.priorities}
    assert factors == {"A": cl.AUTO_RENEW_NO_EXCEPTION_FACTOR, "B": 1.0}


def test_next_fiscal_quarter_end_crosses_the_year():
    assert cl.next_fiscal_quarter_end(date(2026, 10, 17), 9) == date(2026, 12, 31)
    assert cl.next_fiscal_quarter_end(date(2026, 12, 31), 12) == date(2026, 12, 31)
    assert cl.next_fiscal_quarter_end(date(2026, 11, 1), 6) == date(2026, 12, 31)
    assert cl.next_fiscal_quarter_end(date(2026, 10, 17), 1) == date(2026, 10, 31)
