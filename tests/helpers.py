from __future__ import annotations

from datetime import date

from spend_radar.schemas import Vendor


def make_vendor(**overrides) -> Vendor:
    base = {
        "vendor": "Testco",
        "category": "testing",
        "annual_cost": 10000,
        "pricing_model": "per_seat",
        "seats_purchased": 100,
        "seats_active_90d": 90,
        "renewal_date": date(2027, 1, 15),
        "auto_renew": True,
        "notice_days": 30,
        "term_months": 12,
        "owner_team": "Ops",
        "last_uplift_pct": 3.0,
    }
    base.update(overrides)
    return Vendor.model_validate(base)
