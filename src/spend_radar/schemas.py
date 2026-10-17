"""Pydantic models shared by every module."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PricingModel(StrEnum):
    PER_SEAT = "per_seat"
    USAGE = "usage"
    FLAT = "flat"


class RenewalStatus(StrEnum):
    ACT_NOW = "act now"
    UPCOMING = "upcoming"
    WINDOW_CLOSED = "window closed"
    FINE = "fine"


class Vendor(BaseModel):
    vendor: str
    category: str
    annual_cost: float = Field(ge=0)
    pricing_model: PricingModel
    seats_purchased: int = Field(ge=0)
    seats_active_90d: int = Field(ge=0)
    renewal_date: date
    auto_renew: bool
    notice_days: int = Field(ge=0)
    term_months: int = Field(ge=1)
    owner_team: str
    last_uplift_pct: float = Field(ge=0)
    # Who approved an auto-renew exception. Blank means nobody did.
    auto_renew_approved_by: str | None = None

    @field_validator("auto_renew", mode="before")
    @classmethod
    def _parse_bool(cls, value: object) -> object:
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"true", "yes", "y", "1"}:
                return True
            if text in {"false", "no", "n", "0"}:
                return False
        return value

    @field_validator("auto_renew_approved_by", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def slug(self) -> str:
        return "".join(ch for ch in self.vendor.lower() if ch.isalnum())


class RenewalInfo(BaseModel):
    vendor: str
    renewal_date: date
    notice_deadline: date
    days_to_renewal: int
    days_to_deadline: int
    start_negotiating_by: date
    status: RenewalStatus
    auto_renew: bool
    auto_renew_approved_by: str | None = None
    # The next notice deadline if the contract rolls over for another term.
    next_cycle_deadline: date


class UnusedSeatSaving(BaseModel):
    vendor: str
    applicable: bool
    usage_pct: float
    price_per_seat: float
    excess_seats: int = 0
    low: float = 0.0
    high: float = 0.0
    assumption: str


class OverlapMember(BaseModel):
    vendor: str
    annual_cost: float
    seats_active: int
    cost_per_seat: float
    saving_if_moved: float


class OverlapGroup(BaseModel):
    category: str
    members: list[OverlapMember]
    target_vendor: str
    target_cost_per_seat: float
    total_cost: float
    low: float
    high: float
    assumption: str


class PriorityItem(BaseModel):
    rank: int
    vendor: str
    status: RenewalStatus
    saving_low: float
    saving_high: float
    saving_mid: float
    urgency_multiplier: float
    auto_renew_factor: float
    score: float
    why: str


class Urgency(StrEnum):
    NOW = "now"
    SOON = "soon"
    LATER = "later"


class Action(StrEnum):
    ESCALATE_ROLLOVER = "Escalate the rollover"
    NEGOTIATE_NOW = "Negotiate now"
    CONSOLIDATE = "Consolidate"
    RIGHT_SIZE = "Cut unused seats"
    CAP_UPLIFT = "Cap the uplift"
    REMOVE_AUTO_RENEW = "Remove auto-renew"
    WATCH = "Watch"


class Decision(BaseModel):
    vendor: str
    owner_team: str
    action: Action
    urgency: Urgency
    status: RenewalStatus
    headline: str
    decide_by: date
    start_by: date
    annual_cost: float
    saving_low: float = 0.0
    saving_high: float = 0.0
    auto_renew_no_exception: bool = False


class Overview(BaseModel):
    total_spend: float
    saving_low: float
    saving_high: float
    now_count: int
    now_saving_low: float
    now_saving_high: float
    soon_count: int
    later_count: int
    auto_renew_no_exception: int
    auto_renew_total: int
    recommendation: str


class Analysis(BaseModel):
    as_of: date
    total_spend: float
    renewals: list[RenewalInfo]
    unused: list[UnusedSeatSaving]
    overlaps: list[OverlapGroup]
    priorities: list[PriorityItem]
    vendor_saving_low: dict[str, float]
    vendor_saving_high: dict[str, float]
    decisions: list[Decision] = Field(default_factory=list)


Bucket = Literal["situation", "pricing", "competitors", "our_position"]
Origin = Literal["our_data", "fixture", "live"]


class RawItem(BaseModel):
    """One item as a provider returns it, before it gets an id."""

    bucket: Literal["situation", "pricing", "competitors"]
    kind: str = "general"
    title: str
    url: str
    date: date
    snippet: str
    source_type: str


class ProviderResult(BaseModel):
    items: list[RawItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    fiscal_year_end_month: int | None = None


class EvidenceItem(BaseModel):
    id: str
    vendor: str
    bucket: Bucket
    origin: Origin
    kind: str = "general"
    title: str
    url: str
    date: date
    snippet: str
    source_type: str

    @property
    def text(self) -> str:
        return f"{self.title} {self.snippet}"


class Claim(BaseModel):
    text: str
    evidence_id: str = ""
    quote: str = ""


class BriefClaims(BaseModel):
    """Sections 2 to 6 of the brief. Every claim must carry evidence."""

    leverage: list[Claim] = Field(default_factory=list)
    alternatives: list[Claim] = Field(default_factory=list)
    asks: list[Claim] = Field(default_factory=list)
    do_not_reveal: list[Claim] = Field(default_factory=list)
    questions: list[Claim] = Field(default_factory=list)


class FlaggedClaim(BaseModel):
    section: str
    claim: Claim
    reasons: list[str]


class VerificationResult(BaseModel):
    verified: BriefClaims
    flagged: list[FlaggedClaim]

    @property
    def ok(self) -> bool:
        return not self.flagged


class IntelBundle(BaseModel):
    vendor: str
    provider: str
    as_of: date
    items: list[EvidenceItem]
    notes: list[str] = Field(default_factory=list)

    def bucket(self, name: Bucket) -> list[EvidenceItem]:
        return [i for i in self.items if i.bucket == name]

    def get(self, evidence_id: str) -> EvidenceItem | None:
        for item in self.items:
            if item.id == evidence_id:
                return item
        return None


class SnapshotEntry(BaseModel):
    status: RenewalStatus
    urgency: Urgency
    action: Action
    renewal_date: date
    auto_renew: bool
    days_to_deadline: int
    saving_mid: float


class Snapshot(BaseModel):
    """What the portfolio looked like on one run. Saved so the next run can say what changed."""

    as_of: date
    total_spend: float
    vendors: dict[str, SnapshotEntry]


class Change(BaseModel):
    vendor: str
    kind: str
    text: str


class Contact(BaseModel):
    name: str
    email: str
    slack_channel: str | None = None
    # Name of the environment variable that holds the Slack webhook URL. Never the URL itself.
    slack_webhook_env: str | None = None


class NotifyConfig(BaseModel):
    default_owner: Contact
    teams: dict[str, Contact] = Field(default_factory=dict)
