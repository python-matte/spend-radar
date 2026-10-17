# spend-radar

A small command line tool that helps an operations person spend less on software and get more from vendors. It reads a vendor list, finds where money leaks, collects public evidence about each vendor, and writes a negotiation brief where every claim can be checked.

Everything in this repo is invented. The 25 vendors, the costs, the dates and the news items are made up. No real company's contract, price or usage is in here, and no real vendor is a default.

## The problem

Software renewals slip by. A contract auto-renews because nobody saw the notice date. We pay for 300 seats and 138 people log in. Three tools do the same job. A vendor raises the price 9% and nobody asks why.

When someone does sit down to negotiate, the prep takes days. Then a number from a half-remembered article ends up in the email, and the vendor knows it is wrong.

## Before and after

**Before.** A spreadsheet of vendors. Renewal dates in someone's calendar, maybe. A hunch that we pay for too many seats. For a negotiation I would search the news by hand, guess what the competition charges, and write the talking points from memory.

**After.** I run one command and get:

- a one-screen report that starts with a recommendation and the contracts I must decide on now, each with a date and a saving range
- a dashboard: one HTML file with a renewal timeline, savings ranges, seat use and spend by team
- a brief for one vendor. It opens with a recommendation, then: where we stand, what we can use in the room, our alternatives, the asks in order, what to keep quiet, questions, and a dated timeline
- a check on that brief. Every claim names its source and quotes it. If the quote or a number can't be found, the claim goes under a heading that says "Unverified, check before using"
- a monthly digest: one email and one Slack message per team lead, with what changed since last month. It is a dry run unless I pass `--send`

## How I run it

You need Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The commands:

```bash
spend-radar report                   # one screen: recommendation and decisions
spend-radar report --full            # the same, plus the detail tables
spend-radar dashboard --out dash.html   # charts in one HTML file
spend-radar digest                   # monthly email and Slack messages, written to a folder
spend-radar analyze                  # findings and the ranked top 10, printed to the screen
spend-radar analyze --json           # the same, as JSON
spend-radar intel Taskwave           # the evidence collected for one vendor
spend-radar brief Taskwave           # the negotiation brief
```

Useful options:

- `--data path/to/vendors.csv` uses your own list. The columns are in `data/vendors.csv`.
- `--as-of 2026-10-17` sets the date. The default is fixed so results are the same every run.
- `--out file.md` writes to a file.
- `--live` collects real public headlines. It is off by default. See `docs/live-mode.md`.
- `--no-llm` forces the rule-based brief even if a key is set.

### The optional model step

If `ANTHROPIC_API_KEY` is set and the `anthropic` package is installed, the tool asks a model to draft sections 2 to 6 from the evidence. The verifier then checks what comes back. Install the package with:

```bash
pip install -e ".[llm]"
```

The model name comes from `SPEND_RADAR_MODEL`. The default is `claude-sonnet-5-5`. With no key, a rule-based template builds the same brief from the same evidence. The tool works fully without a model.

## What the data looks like

`data/vendors.csv` has 25 invented vendors. The columns are: vendor, category, annual_cost, pricing_model, seats_purchased, seats_active_90d, renewal_date, auto_renew, notice_days, term_months, owner_team, last_uplift_pct, and auto_renew_approved_by.

That last column is mine. A blank means nobody approved an auto-renew exception. My aim is no auto-renew on any contract, so each one without an approval is flagged.

I planted these findings on purpose, and the tests check that each one is found:

- three project management tools and two video meeting tools
- four vendors under 60% seat use
- two vendors whose notice deadline is inside 30 days
- one vendor whose notice window has closed with auto-renew on
- one vendor with a last uplift of 8% or more

`data/intel_fixtures/` has one JSON file per vendor with invented, clearly labelled SAMPLE news, pricing and competitor items. Their links all point at example.com.

## Sample report

This is the whole of `spend-radar report`. The version with the renewals table, overlaps and unused seats is `examples/report_full.md`. A sample brief is `examples/brief_taskwave.md`, and one for a contract whose window has closed is `examples/brief_boardwick.md`.

### At a glance

**Recommendation: Start with Taskwave. Negotiate or give notice by 2026-10-21 (4 days). Planhive is a cheaper option for these seats. Then Meetly, Boardwick.**

- **Decide now:** 3 contracts, with $12,030 to $24,060 a year at stake. These are inside the notice window or already locked in.
- **Coming up:** 5 more decisions in the next 90 days. 13 later.
- **Spend:** $619,800 a year. Rough recoverable range $51,688 to $103,375. Estimates, not promises.
- **Auto-renew:** 19 of 20 auto-renew contracts have no approved exception. The goal is none.

### Decide now

| Vendor | Team | Action | Decide by | Saving a year | What to do |
|---|---|---|---|---|---|
| **Taskwave** | Engineering | Negotiate now | 2026-10-21 | $6,150 to $12,300 | Negotiate or give notice by 2026-10-21 (4 days). Planhive is a cheaper option for these seats. |
| **Meetly** | IT | Negotiate now | 2026-10-31 | $3,180 to $6,360 | Negotiate or give notice by 2026-10-31 (14 days). 53 seats are unused. |
| **Boardwick** | Operations | Escalate the rollover | 2026-11-12 | $2,700 to $5,400 | Ask in writing to be released from the rollover on 2026-11-12. The notice deadline passed 19 days ago. |

### Coming up (next 90 days)

| Vendor | Team | Action | Decide by | Saving a year | What to do |
|---|---|---|---|---|---|
| **Cloudpebble** | IT | Cut unused seats | 2026-12-12 | $13,320 to $26,640 | Cut 148 unused seats at renewal. Only 46% of seats are in use. Decide by 2026-12-12. |
| **Hirestack** | People | Cut unused seats | 2027-01-08 | $4,200 to $8,400 | Cut 16 unused seats at renewal. Only 52% of seats are in use. Decide by 2027-01-08. |
| **Designmint** | Marketing | Cut unused seats | 2027-01-06 | $3,795 to $7,590 | Cut 23 unused seats at renewal. Only 55% of seats are in use. Decide by 2027-01-06. |
| **Chatharbor** | IT | Cap the uplift | 2026-12-06 | $1,140 to $2,280 | Cap the uplift. The last one was 9.5%. Decide by 2026-12-06. |
| **Signalforge** | Support | Remove auto-renew | 2026-12-07 | $600 to $1,200 | Ask to remove auto-renew. Decide by 2026-12-07. |

### Later (13)

Planhive, Insightpine, Huddlefox, Voxdesk, Quillboard, Payloom, Calendrift, Securenook, Codepillar, Datanest, Docuvane, Formkiln, Pingmoss.

### Auto-renew watchlist, soonest first

| Vendor | Notice deadline | Days | Rolls over on | Approved exception |
|---|---|---|---|---|
| Boardwick | 2026-09-28 | 19 ago | 2026-11-12 | NONE |
| Taskwave | 2026-10-21 | 4 | 2026-12-20 | NONE |
| Meetly | 2026-10-31 | 14 | 2026-11-30 | NONE |
| Ledgerleaf | 2026-12-02 | 46 | 2027-01-31 | Head of Finance |
| Chatharbor | 2026-12-06 | 50 | 2027-01-20 | NONE |

15 more auto-renew contracts are in the full report.

## Dashboard

`spend-radar dashboard` writes one HTML file. Open it in a browser. It has four views: when each decision falls due, where the money is, seats we pay for but do not use, and spend by team. It has no scripts and makes no outside requests. Hover a row for details. The timeline has a table view. A sample is `examples/dashboard.html`.

## Monthly digest

`spend-radar digest` builds one email and one Slack message per recipient. The spend owner gets everything and the dashboard. Each team lead gets only their own vendors. Each message has a recommendation first, then what to decide now, what is coming up, and what changed since last month.

By default it only writes the messages to a folder. It sends nothing. Sending needs `--send`, real contacts and credentials in environment variables. The samples in `examples/digest/` use placeholder addresses. I show how I would schedule it in `docs/monthly-run.md`. I have not scheduled or sent anything.

## The verifier

The part I care about most. The brief is a list of claims. Each claim carries an `evidence_id` and a `quote`. `verify_brief()` checks three things:

1. the evidence id exists
2. the quote appears word for word in that evidence item
3. every number and date in the claim appears in our data or in the evidence

Anything that fails is listed under "Unverified, check before using" with the reasons. It is never kept quietly. Details are in `docs/verifier.md`.

## Limitations

- **These are estimates.** The saving ranges come from simple rules and the assumptions printed next to them. They are not quotes.
- **Not legal or financial advice.** I am not a lawyer or a financial adviser, and neither is this tool.
- **Verify before you quote anything.** The verifier checks that words and numbers match the evidence. It cannot tell you the evidence is true, and it cannot tell you a claim means what the quote means. Read the source before you say anything in a negotiation.
- **The fixtures are fictional.** Every vendor and news item here is invented. Do not take any of it into a real meeting.
- **Cost per seat is a blunt average.** Real contracts have tiers, minimums and add-ons that a CSV does not hold.
- **Live mode is thin.** It reads headlines and one optional pricing page. It does not search for competitors. I tested it with fake HTTP clients, not the real network.
- **Category savings can overlap.** The portfolio total is a rough upper sketch.
- **Decisions are rules, not judgment.** "Decide now" means the notice window is open and close, or has closed. A person still has to decide.
- **Sending is untested for real.** The email and Slack code was tested with fake servers. It has never sent a real message.
- **"Last month" in the samples is simulated.** I ran the tool with an earlier date to make a first snapshot.
- **Dashboard dark mode is unchecked.** I looked at it in light mode on desktop and phone width. The dark colours follow a validated palette, but I have not seen them rendered.

## Project layout

```
src/spend_radar/
  core_logic.py   all the math, no I/O, no network, no model
  schemas.py      pydantic models
  intel.py        fixture and live providers, cache, evidence
  brief.py        brief builder, model step and the verifier
  cli.py          analyze, intel, brief, report
  loader.py       reads the CSV
  report.py       portfolio report
  dashboard.py    one-file HTML dashboard
  digest.py       monthly email and Slack messages, snapshots
  notify.py       sending, with checks first
config/           notify.example.json (placeholder contacts)
data/             vendors.csv and intel_fixtures/
examples/         committed sample outputs
tests/            pytest
docs/             how the numbers work, the verifier, live mode, the monthly run
```

## Tests and CI

```bash
pytest
ruff check .
ruff format --check .
```

GitHub Actions runs ruff and pytest on Python 3.11 and 3.13.

## More

- `BUILT_WITH_AI.md` says how this was built.
- `LICENSE` is MIT.
