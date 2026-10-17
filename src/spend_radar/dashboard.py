"""One self-contained HTML dashboard. No scripts, no external requests, no server."""

from __future__ import annotations

from collections import defaultdict
from html import escape

from . import core_logic as cl
from .core_logic import money
from .schemas import Analysis, Decision, RenewalStatus, Urgency, Vendor

SVG_NS = "http://www.w3.org/2000/svg"

# Shape and colour per status. Colour is never the only signal: each status has its own shape
# and a text label.
STATUS_STYLE = {
    RenewalStatus.ACT_NOW: ("circle", "var(--crit)", "Act now"),
    RenewalStatus.WINDOW_CLOSED: ("diamond", "var(--serious)", "Window closed"),
    RenewalStatus.UPCOMING: ("triangle", "var(--warn)", "Upcoming"),
    RenewalStatus.FINE: ("square", "var(--neutral)", "Fine"),
}

CSS = """
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --series: #2a78d6; --series-soft: #9ec5f4;
  --crit: #d03b3b; --serious: #ec835a; --warn: #fab219; --neutral: #898781;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --series: #3987e5; --series-soft: #1c5cab;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --series: #3987e5; --series-soft: #1c5cab;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1120px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 24px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 0 0 4px; }
p { margin: 0; }
.sub { color: var(--ink2); }
.banner { margin: 16px 0; padding: 10px 14px; border: 1px solid var(--border);
  background: var(--surface); border-radius: 8px; color: var(--ink2); }
.reco { margin: 16px 0; padding: 16px; border: 1px solid var(--border); background: var(--surface);
  border-left: 4px solid var(--crit); border-radius: 8px; font-size: 16px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px;
  margin: 16px 0; }
.tile { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 14px 16px; }
.tile .v { font-size: 26px; font-weight: 600; line-height: 1.2; }
.tile .l { color: var(--ink2); font-size: 13px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 16px; margin: 16px 0; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 8px 0 12px; color: var(--ink2);
  font-size: 13px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.key { width: 12px; height: 12px; display: inline-block; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--grid);
  vertical-align: top; }
th { color: var(--ink2); font-weight: 600; font-size: 13px; }
.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
.tag { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.row { display: grid; grid-template-columns: 120px 1fr 190px; gap: 10px; align-items: center;
  padding: 4px 0; }
.row:hover { background: var(--page); }
.row .name { color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row .val { color: var(--ink2); font-size: 13px; text-align: right; }
.track { position: relative; height: 14px; background: var(--grid); border-radius: 0 4px 4px 0; }
.seg { position: absolute; top: 0; bottom: 0; border-radius: 0 4px 4px 0; }
.thr { position: absolute; top: -4px; bottom: -4px; width: 0; border-left: 2px dashed var(--ink2); }
.thr-label { position: absolute; top: -22px; transform: translateX(-50%); font-size: 12px;
  color: var(--ink2); }
details { margin-top: 12px; color: var(--ink2); }
summary { cursor: pointer; }
footer { color: var(--muted); font-size: 13px; margin-top: 24px; }
@media (max-width: 640px) {
  .row { grid-template-columns: 90px 1fr; }
  .row .val { grid-column: 1 / -1; text-align: left; }
}
"""


def _marker(shape: str, cx: float, cy: float, color: str, size: float = 10) -> str:
    r = size / 2
    common = f'fill="{color}" stroke="var(--surface)" stroke-width="2"'
    if shape == "circle":
        return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" {common}/>'
    if shape == "square":
        return f'<rect x="{cx - r:.1f}" y="{cy - r:.1f}" width="{size}" height="{size}" {common}/>'
    if shape == "diamond":
        pts = f"{cx:.1f},{cy - r - 1:.1f} {cx + r + 1:.1f},{cy:.1f} {cx:.1f},{cy + r + 1:.1f} {cx - r - 1:.1f},{cy:.1f}"
    else:  # triangle
        pts = (
            f"{cx:.1f},{cy - r - 1:.1f} {cx + r + 1:.1f},{cy + r:.1f} {cx - r - 1:.1f},{cy + r:.1f}"
        )
    return f'<polygon points="{pts}" {common}/>'


def _legend_status() -> str:
    items = []
    for status in RenewalStatus:
        shape, color, label = STATUS_STYLE[status]
        svg = f'<svg width="14" height="14" viewBox="0 0 14 14" xmlns="{SVG_NS}">{_marker(shape, 7, 7, color, 9)}</svg>'
        items.append(f"<span>{svg}{escape(label)}</span>")
    return f'<div class="legend">{"".join(items)}</div>'


def _tile(value: str, label: str) -> str:
    return f'<div class="tile"><div class="v">{escape(value)}</div><div class="l">{escape(label)}</div></div>'


def _status_tag(status: RenewalStatus) -> str:
    shape, color, label = STATUS_STYLE[status]
    svg = f'<svg width="14" height="14" viewBox="0 0 14 14" xmlns="{SVG_NS}" aria-hidden="true">{_marker(shape, 7, 7, color, 9)}</svg>'
    return f'<span class="tag">{svg}{escape(label)}</span>'


def _decisions_table(decisions: list[Decision]) -> str:
    rows = []
    for d in decisions:
        saving = (
            f"{money(round(d.saving_low))} to {money(round(d.saving_high))}"
            if d.saving_high > 0
            else "no estimate"
        )
        rows.append(
            "<tr>"
            f"<td><strong>{escape(d.vendor)}</strong><br><span class='sub'>{escape(d.owner_team)}</span></td>"
            f"<td>{_status_tag(d.status)}</td>"
            f"<td>{escape(d.action.value)}</td>"
            f"<td class='num'>{d.decide_by.isoformat()}</td>"
            f"<td class='num'>{escape(saving)}</td>"
            f"<td>{escape(d.headline)}</td>"
            "</tr>"
        )
    head = "<tr><th>Vendor</th><th>Status</th><th>Action</th><th>Decide by</th><th>Saving a year</th><th>What to do</th></tr>"
    return f'<div class="scroll"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def _timeline(vendors: list[Vendor], analysis: Analysis) -> str:
    by_name = {v.vendor: v for v in vendors}
    rows = sorted(
        analysis.renewals,
        key=lambda r: (
            r.notice_deadline if by_name[r.vendor].auto_renew else r.renewal_date,
            r.vendor,
        ),
    )
    lo, hi = -30, 240
    left, right, top, row_h = 130, 24, 34, 22
    width = 860
    plot_w = width - left - right
    height = top + row_h * len(rows) + 28

    def x(days: int) -> float:
        return left + (min(max(days, lo), hi) - lo) / (hi - lo) * plot_w

    parts = [
        f'<svg xmlns="{SVG_NS}" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        'role="img" aria-label="Renewal timeline. One row per vendor, ordered by decision date.">'
    ]
    for days, label in ((0, "Today"), (30, "+30 days"), (90, "+90 days"), (180, "+180 days")):
        dash = "" if days == 0 else ' stroke-dasharray="3 4"'
        color = "var(--ink2)" if days == 0 else "var(--axis)"
        parts.append(
            f'<line x1="{x(days):.1f}" x2="{x(days):.1f}" y1="{top - 6}" y2="{height - 22}" '
            f'stroke="{color}" stroke-width="1"{dash}/>'
            f'<text x="{x(days):.1f}" y="{top - 12}" text-anchor="middle" font-size="12" '
            f'fill="var(--ink2)">{label}</text>'
        )
    for i, r in enumerate(rows):
        v = by_name[r.vendor]
        cy = top + i * row_h + row_h / 2
        mark_day = r.days_to_deadline if v.auto_renew else r.days_to_renewal
        shape, color, label = STATUS_STYLE[r.status]
        ren_day = r.days_to_renewal
        what = "notice deadline" if v.auto_renew else "renewal date"
        tip = (
            f"{r.vendor}: {label}. {what} in {mark_day} days"
            if mark_day >= 0
            else f"{r.vendor}: {label}. Notice deadline passed {-mark_day} days ago"
        )
        tip += (
            f". Renews {r.renewal_date.isoformat()}. Auto-renew {'on' if v.auto_renew else 'off'}."
        )
        parts.append(
            f"<g><title>{escape(tip)}</title>"
            f'<rect x="{left - 4}" y="{cy - row_h / 2:.1f}" width="{plot_w + 8}" height="{row_h}" fill="transparent"/>'
            f'<text x="{left - 10}" y="{cy + 4:.1f}" text-anchor="end" font-size="13" '
            f'fill="var(--ink)">{escape(r.vendor)}</text>'
            f'<line x1="{x(mark_day):.1f}" x2="{x(ren_day):.1f}" y1="{cy:.1f}" y2="{cy:.1f}" '
            f'stroke="var(--axis)" stroke-width="2" stroke-linecap="round"/>'
            f'<line x1="{x(ren_day):.1f}" x2="{x(ren_day):.1f}" y1="{cy - 4:.1f}" y2="{cy + 4:.1f}" '
            f'stroke="var(--ink2)" stroke-width="2"/>'
            f"{_marker(shape, x(mark_day), cy, color)}</g>"
        )
    parts.append(
        f'<text x="{left}" y="{height - 6}" font-size="12" fill="var(--ink2)">'
        "Marker: notice deadline (renewal date if no auto-renew). Line: time until renewal. "
        "Tick: renewal date.</text></svg>"
    )

    table_rows = "".join(
        f"<tr><td>{escape(r.vendor)}</td><td class='num'>{r.notice_deadline.isoformat()}</td>"
        f"<td class='num'>{r.days_to_deadline}</td><td class='num'>{r.renewal_date.isoformat()}</td>"
        f"<td>{escape(STATUS_STYLE[r.status][2])}</td>"
        f"<td>{'on' if by_name[r.vendor].auto_renew else 'off'}</td></tr>"
        for r in rows
    )
    table = (
        "<details><summary>Table view</summary><div class='scroll'><table><thead><tr>"
        "<th>Vendor</th><th>Notice deadline</th><th>Days</th><th>Renewal</th><th>Status</th>"
        "<th>Auto-renew</th></tr></thead><tbody>" + table_rows + "</tbody></table></div></details>"
    )
    return (
        '<section class="card"><h2>When decisions fall due</h2>'
        '<p class="sub">Each row is a contract. The closer the marker is to Today, the sooner '
        "you must act.</p>"
        + _legend_status()
        + f'<div class="scroll">{"".join(parts)}</div>'
        + table
        + "</section>"
    )


def _savings_chart(analysis: Analysis) -> str:
    items = analysis.priorities
    top = max((p.saving_high for p in items), default=1) or 1
    rows = []
    for p in items:
        low_w = p.saving_low / top * 100
        high_w = p.saving_high / top * 100
        tip = f"{p.vendor}: {money(round(p.saving_low))} to {money(round(p.saving_high))} a year. {p.why}"
        rows.append(
            f'<div class="row" title="{escape(tip)}"><div class="name">{escape(p.vendor)}</div>'
            '<div class="track">'
            f'<div class="seg" style="left:0;width:{high_w:.1f}%;background:var(--series-soft)"></div>'
            f'<div class="seg" style="left:0;width:calc({low_w:.1f}% - 2px);background:var(--series)"></div>'
            "</div>"
            f'<div class="val">{money(round(p.saving_low))} to {money(round(p.saving_high))}</div></div>'
        )
    legend = (
        '<div class="legend"><span><i class="key" style="background:var(--series)"></i>Low case</span>'
        '<span><i class="key" style="background:var(--series-soft)"></i>Added in the high case</span></div>'
    )
    return (
        '<section class="card"><h2>Where the money is</h2>'
        '<p class="sub">Top 10 by priority score. Each bar is a range, never one number.</p>'
        + legend
        + "".join(rows)
        + "</section>"
    )


def _usage_chart(vendors: list[Vendor]) -> str:
    ordered = sorted(vendors, key=lambda v: (cl.seat_usage_pct(v), v.vendor))
    rows = []
    for v in ordered:
        usage = cl.seat_usage_pct(v)
        low = usage < cl.LOW_USAGE_PCT
        color = "var(--serious)" if low else "var(--series)"
        tag = " (below 60%)" if low else ""
        tip = f"{v.vendor}: {v.seats_active_90d} of {v.seats_purchased} seats active, {usage:.0f}%."
        rows.append(
            f'<div class="row" title="{escape(tip)}"><div class="name">{escape(v.vendor)}</div>'
            f'<div class="track"><div class="seg" style="left:0;width:{usage:.1f}%;background:{color}"></div>'
            f'<div class="thr" style="left:{cl.LOW_USAGE_PCT}%"></div></div>'
            f'<div class="val">{usage:.0f}% · {v.seats_active_90d} of {v.seats_purchased}{tag}</div></div>'
        )
    legend = (
        '<div class="legend"><span><i class="key" style="background:var(--series)"></i>Seats in use</span>'
        '<span><i class="key" style="background:var(--serious)"></i>Under the 60% line</span>'
        "<span>Dashed line: 60% use</span></div>"
    )
    return (
        '<section class="card"><h2>Seats we pay for but do not use</h2>'
        '<p class="sub">Share of purchased seats that were active in the last 90 days, lowest first.</p>'
        + legend
        + "".join(rows)
        + "</section>"
    )


def _team_chart(vendors: list[Vendor], analysis: Analysis) -> str:
    cost: dict[str, float] = defaultdict(float)
    todo: dict[str, int] = defaultdict(int)
    for v in vendors:
        cost[v.owner_team] += v.annual_cost
    for d in cl.actionable(analysis.decisions):
        if d.urgency is not Urgency.LATER:
            todo[d.owner_team] += 1
    top = max(cost.values(), default=1) or 1
    rows = []
    for team, amount in sorted(cost.items(), key=lambda kv: (-kv[1], kv[0])):
        n = todo[team]
        note = f" · {n} decision{'s' if n != 1 else ''} due" if n else ""
        tip = f"{team}: {money(amount)} a year{note}."
        rows.append(
            f'<div class="row" title="{escape(tip)}"><div class="name">{escape(team)}</div>'
            f'<div class="track"><div class="seg" style="left:0;width:{amount / top * 100:.1f}%;background:var(--series)"></div></div>'
            f'<div class="val">{money(amount)}{escape(note)}</div></div>'
        )
    return (
        '<section class="card"><h2>Spend by owner team</h2>'
        '<p class="sub">Annual cost by the team that owns the contract. Also how many decisions '
        "fall due in the next 90 days.</p>" + "".join(rows) + "</section>"
    )


def render_dashboard(vendors: list[Vendor], analysis: Analysis, sample: bool = True) -> str:
    ov = cl.build_overview(vendors, analysis)
    todo = cl.actionable(analysis.decisions)
    urgent = [d for d in todo if d.urgency in (Urgency.NOW, Urgency.SOON)]
    banner = (
        '<p class="banner"><strong>SAMPLE DATA.</strong> Every vendor, cost and date here is '
        "invented for demonstration.</p>"
        if sample
        else ""
    )
    tiles = "".join(
        [
            _tile(
                f"{ov.now_count} to decide now",
                f"{money(round(ov.now_saving_low))} to {money(round(ov.now_saving_high))} a year at stake",
            ),
            _tile(money(ov.total_spend), f"annual software spend across {len(vendors)} vendors"),
            _tile(
                f"{money(round(ov.saving_low))} to {money(round(ov.saving_high))}",
                "rough recoverable range a year (estimate)",
            ),
            _tile(
                f"{ov.auto_renew_no_exception} of {ov.auto_renew_total}",
                "auto-renew contracts with no approved exception",
            ),
        ]
    )
    body = [
        f"<h1>Spend radar</h1><p class='sub'>As of {analysis.as_of.isoformat()}. "
        "Where software money leaks and what to decide next.</p>",
        banner,
        f'<div class="reco"><strong>Recommendation.</strong> {escape(ov.recommendation)}</div>',
        f'<div class="kpis">{tiles}</div>',
        '<section class="card"><h2>Decide now and next 90 days</h2>'
        + _decisions_table(urgent)
        + "</section>",
        _timeline(vendors, analysis),
        _savings_chart(analysis),
        _usage_chart(vendors),
        _team_chart(vendors, analysis),
        "<footer>Estimates, not quotes. Not legal or financial advice. Check every figure against "
        "the contract. Generated by spend-radar.</footer>",
    ]
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Spend Radar Dashboard</title>"
        f"<style>{CSS}</style></head><body><main>{''.join(body)}</main></body></html>\n"
    )
