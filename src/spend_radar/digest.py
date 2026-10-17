"""The monthly digest: one email and one Slack message per recipient.

This module only builds messages and reads or writes state files. Sending lives in notify.py.
By default nothing is sent. The messages are written to a folder so you can read them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from html import escape
from pathlib import Path

from . import core_logic as cl
from .core_logic import money
from .schemas import (
    Analysis,
    Change,
    Contact,
    Decision,
    NotifyConfig,
    Snapshot,
    Urgency,
    Vendor,
)

SLACK_SECTION_LIMIT = 2800
MAX_LINES_PER_BLOCK = 8


@dataclass
class Message:
    recipient_key: str
    contact: Contact
    subject: str
    sections: list[tuple[str, list[str]]]
    footer: str
    attach_dashboard: bool = False
    notes: list[str] = field(default_factory=list)

    # Renderings -------------------------------------------------------------------------

    def email_text(self) -> str:
        lines = [f"Hi {self.contact.name},", ""]
        for title, body in self.sections:
            if title:
                lines += [title.upper(), ""]
            lines += body + [""]
        if self.attach_dashboard:
            lines += ["The dashboard is attached (dashboard.html). Open it in a browser.", ""]
        lines += [self.footer]
        return "\n".join(lines).rstrip() + "\n"

    def email_html(self) -> str:
        out = [
            '<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;'
            'max-width:640px;color:#0b0b0b;line-height:1.5">',
            f"<p>Hi {escape(self.contact.name)},</p>",
        ]
        for title, body in self.sections:
            if title:
                out.append(f'<h3 style="margin:20px 0 6px;font-size:16px">{escape(title)}</h3>')
            bullets = [b for b in body if b.startswith("- ")]
            plain = [b for b in body if not b.startswith("- ") and b]
            out += [f"<p>{escape(b)}</p>" for b in plain]
            if bullets:
                out.append("<ul>" + "".join(f"<li>{escape(b[2:])}</li>" for b in bullets) + "</ul>")
        if self.attach_dashboard:
            out.append("<p>The dashboard is attached (dashboard.html). Open it in a browser.</p>")
        out.append(f'<p style="color:#52514e;font-size:13px">{escape(self.footer)}</p></div>')
        return "".join(out)

    def slack_payload(self) -> dict:
        def esc(text: str) -> str:
            return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        blocks: list[dict] = [
            {"type": "header", "text": {"type": "plain_text", "text": self.subject[:150]}}
        ]
        for title, body in self.sections:
            text = ("*" + esc(title) + "*\n" if title else "") + "\n".join(
                ("• " + esc(b[2:])) if b.startswith("- ") else esc(b) for b in body
            )
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": text[:SLACK_SECTION_LIMIT]}}
            )
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": esc(self.footer)}]}
        )
        payload: dict = {"text": self.subject, "blocks": blocks}
        if self.contact.slack_channel:
            payload["channel"] = self.contact.slack_channel
        return payload


# Building ---------------------------------------------------------------------------------


def _range(low: float, high: float) -> str:
    return f"{money(round(low))} to {money(round(high))}"


def _decision_line(d: Decision) -> str:
    saving = f", {_range(d.saving_low, d.saving_high)} a year" if d.saving_high > 0 else ""
    return f"- {d.vendor} ({d.owner_team}){saving}: {d.headline}"


def _capped(lines: list[str], noun: str) -> list[str]:
    if len(lines) <= MAX_LINES_PER_BLOCK:
        return lines
    extra = len(lines) - MAX_LINES_PER_BLOCK
    return lines[:MAX_LINES_PER_BLOCK] + [f"- ...and {extra} more {noun} in the dashboard."]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "recipient"


def month_label(as_of: date) -> str:
    return as_of.strftime("%B %Y")


def build_digest(
    vendors: list[Vendor],
    analysis: Analysis,
    changes: list[Change],
    config: NotifyConfig,
    previous: Snapshot | None,
    sample: bool = True,
) -> list[Message]:
    label = month_label(analysis.as_of)
    todo = cl.actionable(analysis.decisions)
    footer = (
        "Estimates, not quotes. Not legal or financial advice. Check every figure against the "
        "contract before acting."
    )
    if sample:
        footer = "SAMPLE DATA, all invented. " + footer
    since = (
        f"What changed since {previous.as_of.isoformat()}"
        if previous
        else "What changed since last month"
    )
    teams = sorted({v.owner_team for v in vendors})
    messages: list[Message] = []

    def sections_for(
        decisions: list[Decision], changed: list[Change], owner_view: bool, scope: str
    ) -> tuple[list[tuple[str, list[str]]], str]:
        now = [d for d in decisions if d.urgency is Urgency.NOW]
        soon = [d for d in decisions if d.urgency is Urgency.SOON]
        low = sum(d.saving_low for d in now)
        high = sum(d.saving_high for d in now)
        if owner_view:
            reco = cl.build_overview(vendors, analysis).recommendation
        elif now:
            reco = f"Start with {now[0].vendor}. {now[0].headline}"
        else:
            reco = f"Prepare {soon[0].vendor} next. {soon[0].headline}"
        subject = (
            f"[Spend radar] {label}: {len(now)} decision{'s' if len(now) != 1 else ''} due now"
            + (f", {_range(low, high)} at stake" if now and high > 0 else "")
            + (f" ({scope})" if scope else "")
        )
        secs: list[tuple[str, list[str]]] = [("Recommendation", [reco])]
        secs.append(
            (
                "Decide now",
                _capped([_decision_line(d) for d in now], "decisions")
                or ["Nothing is inside the notice window."],
            )
        )
        secs.append(
            (
                "Coming up (next 90 days)",
                _capped([_decision_line(d) for d in soon], "decisions")
                or ["Nothing in the next 90 days."],
            )
        )
        if previous is None:
            secs.append((since, ["First run. There is nothing to compare with yet."]))
        elif changed:
            secs.append((since, _capped([f"- {c.vendor}: {c.text}" for c in changed], "changes")))
        else:
            secs.append((since, ["No changes."]))
        return secs, subject

    # The spend owner gets the whole picture and the dashboard.
    secs, subject = sections_for(analysis.decisions, changes, True, "")
    secs = [(t, b) for t, b in secs]
    no_exception = [v for v in vendors if v.auto_renew and not v.auto_renew_approved_by]
    secs.append(
        (
            "Auto-renew watch",
            [
                f"{len(no_exception)} of {sum(1 for v in vendors if v.auto_renew)} auto-renew "
                "contracts have no approved exception. The goal is none."
            ],
        )
    )
    unconfigured = [t for t in teams if t not in config.teams]
    notes = []
    if unconfigured:
        notes.append(
            "No team contact is configured for: "
            + ", ".join(unconfigured)
            + ". Their decisions are "
            "in this message only."
        )
        secs.append(("Teams without a contact", [notes[0]]))
    messages.append(
        Message(
            recipient_key="default-owner",
            contact=config.default_owner,
            subject=subject,
            sections=secs,
            footer=footer,
            attach_dashboard=True,
            notes=notes,
        )
    )

    # Each configured team gets only its own vendors.
    for team in teams:
        contact = config.teams.get(team)
        if contact is None:
            continue
        mine = {v.vendor for v in vendors if v.owner_team == team}
        decisions = [d for d in todo if d.vendor in mine and d.urgency is not Urgency.LATER]
        if not decisions:
            continue
        changed = [c for c in changes if c.vendor in mine]
        team_secs, team_subject = sections_for(decisions, changed, False, team)
        spend = sum(v.annual_cost for v in vendors if v.owner_team == team)
        team_secs.insert(
            1, ("Your spend", [f"{team} owns {len(mine)} contracts worth {money(spend)} a year."])
        )
        messages.append(
            Message(
                recipient_key=f"team-{_slug(team)}",
                contact=contact,
                subject=team_subject,
                sections=team_secs,
                footer=footer,
            )
        )
    return messages


# State ------------------------------------------------------------------------------------


def load_previous_snapshot(state_dir: Path, as_of: date) -> Snapshot | None:
    """Most recent saved snapshot taken before as_of."""
    best: Snapshot | None = None
    if not state_dir.exists():
        return None
    for path in state_dir.glob("snapshot-*.json"):
        try:
            snap = Snapshot.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if snap.as_of < as_of and (best is None or snap.as_of > best.as_of):
            best = snap
    return best


def save_snapshot(state_dir: Path, snapshot: Snapshot) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"snapshot-{snapshot.as_of.isoformat()}.json"
    path.write_text(snapshot.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


# Dry run ----------------------------------------------------------------------------------


def write_dry_run(messages: list[Message], out_dir: Path, dashboard_html: str) -> list[Path]:
    """Write every message to disk so a person can read it. Sends nothing."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    (out_dir / "dashboard.html").write_text(dashboard_html, encoding="utf-8")
    written.append(out_dir / "dashboard.html")
    for m in messages:
        folder = out_dir / m.recipient_key
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "email.txt").write_text(
            f"To: {m.contact.name} <{m.contact.email}>\nSubject: {m.subject}\n\n{m.email_text()}",
            encoding="utf-8",
        )
        (folder / "email.html").write_text(m.email_html(), encoding="utf-8")
        (folder / "slack.json").write_text(
            json.dumps(m.slack_payload(), indent=2) + "\n", encoding="utf-8"
        )
        written += [folder / "email.txt", folder / "email.html", folder / "slack.json"]
    return written
