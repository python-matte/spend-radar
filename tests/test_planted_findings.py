"""The synthetic data plants specific findings. Each test asserts the tool finds them."""

from __future__ import annotations

from spend_radar import core_logic as cl
from spend_radar.loader import AS_OF
from spend_radar.schemas import RenewalStatus


def test_25_invented_vendors_and_fixed_as_of(vendors):
    assert len(vendors) == 25
    assert AS_OF.isoformat() == "2026-10-17"


def test_overlap_groups_are_project_management_and_video_meetings(analysis):
    groups = {g.category: sorted(m.vendor for m in g.members) for g in analysis.overlaps}
    assert groups == {
        "project management": ["Boardwick", "Planhive", "Taskwave"],
        "video meetings": ["Huddlefox", "Meetly"],
    }


def test_four_vendors_under_60_percent_usage(vendors):
    names = sorted(v.vendor for v in cl.low_usage_vendors(vendors))
    assert names == ["Cloudpebble", "Designmint", "Hirestack", "Planhive"]


def test_two_notice_deadlines_inside_30_days(analysis):
    inside = [r.vendor for r in analysis.renewals if 0 <= r.days_to_deadline <= 30]
    assert sorted(inside) == ["Meetly", "Taskwave"]
    assert all(r.status is RenewalStatus.ACT_NOW for r in analysis.renewals if r.vendor in inside)


def test_one_closed_window_with_auto_renew_on(vendors, analysis):
    closed = [r for r in analysis.renewals if r.status is RenewalStatus.WINDOW_CLOSED]
    assert [r.vendor for r in closed] == ["Boardwick"]
    assert closed[0].auto_renew is True
    assert closed[0].days_to_deadline < 0


def test_one_vendor_with_uplift_of_8_percent_or_more(vendors):
    assert [v.vendor for v in cl.high_uplift_vendors(vendors)] == ["Chatharbor"]


def test_approved_auto_renew_exception_is_tracked(vendors):
    approved = [v.vendor for v in vendors if v.auto_renew and v.auto_renew_approved_by]
    unapproved = [v for v in vendors if v.auto_renew and not v.auto_renew_approved_by]
    assert approved == ["Ledgerleaf"]
    assert len(unapproved) == 19
