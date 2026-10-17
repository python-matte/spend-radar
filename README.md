# spend-radar

A small command line tool that helps an operations person spend less on software and get more from vendors. It reads a vendor list, finds where money leaks, collects public evidence about each vendor, and writes a negotiation brief where every claim can be checked.

Everything in this repo is invented. The 25 vendors, the costs, the dates and the news items are made up. No real company's contract, price or usage is in here, and no real vendor is a default.

## The problem

Software renewals slip by. A contract auto-renews because nobody saw the notice date. We pay for 300 seats and 138 people log in. Three tools do the same job. A vendor raises the price 9% and nobody asks why.

When someone does sit down to negotiate, the prep takes days. Then a number from a half-remembered article ends up in the email, and the vendor knows it is wrong.

## Before and after

**Before.** A spreadsheet of vendors. Renewal dates in someone's calendar, maybe. A hunch that we pay for too many seats. For a negotiation I would search the news by hand, guess what the competition charges, and write the talking points from memory.

**After.** I run one command and get:

- a list of contracts that roll over by themselves, soonest deadline first
- a ranked top 10 of where the money is, with a low and a high estimate and the assumption next to each
- a brief for one vendor: where we stand, what we can use in the room, our alternatives, the asks in order, what to keep quiet, questions, and a dated timeline
- a check on that brief. Every claim names its source and quotes it. If the quote or a number can't be found, the claim goes under a heading that says "Unverified, check before using"

## How I run it

You need Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The commands:

```bash
spend-radar analyze                  # findings and the ranked top 10, printed to the screen
spend-radar analyze --json           # the same, as JSON
spend-radar intel Taskwave           # the evidence collected for one vendor
spend-radar brief Taskwave           # the negotiation brief
spend-radar report --out report.md   # the full portfolio report
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

This is from `spend-radar report`. The full version, including the renewals table, overlaps and unused seats, is in `examples/report.md`. A sample brief is in `examples/brief_taskwave.md`. A brief for a contract whose window has closed is in `examples/brief_boardwick.md`.

### Summary

- Total annual software spend: $619,800.
- Estimated recoverable: $51,688 to $103,375 a year. This is a range built from stated assumptions. It is not a promise. Savings inside one category can overlap, so read the total as a rough upper sketch.
- Notice deadline in the next 30 days: 2.
- Notice window already closed with auto-renew on: 1.
- Vendors under 60% seat usage: 4.
- Vendors with a last uplift of 8% or more: 1.
- Categories with more than one vendor: 2.
- Contracts on auto-renew: 20. Of those, 19 have no approved exception.

### Auto-renew watchlist

Our goal is no auto-renew on any contract. Each line below rolls over unless we act by the notice deadline. An approved exception is the rare case.

| Vendor | Annual cost | Notice deadline | Days | Rolls over on | Status | Approved exception |
|---|---|---|---|---|---|---|
| Boardwick | $26,400 | 2026-09-28 | 19 ago | 2026-11-12 | window closed | NONE |
| Taskwave | $48,000 | 2026-10-21 | 4 | 2026-12-20 | act now | NONE |
| Meetly | $22,800 | 2026-10-31 | 14 | 2026-11-30 | act now | NONE |
| Ledgerleaf | $18,600 | 2026-12-02 | 46 | 2027-01-31 | upcoming | Head of Finance |
| Chatharbor | $36,000 | 2026-12-06 | 50 | 2027-01-20 | upcoming | NONE |
| Signalforge | $42,000 | 2026-12-07 | 51 | 2027-02-05 | upcoming | NONE |
| Cloudpebble | $54,000 | 2026-12-12 | 56 | 2027-02-10 | upcoming | NONE |
| Designmint | $19,800 | 2027-01-06 | 81 | 2027-02-20 | upcoming | NONE |
| Planhive | $31,500 | 2027-01-29 | 104 | 2027-03-15 | fine | NONE |
| Docuvane | $9,600 | 2027-01-30 | 105 | 2027-03-01 | fine | NONE |
| Quillboard | $13,500 | 2027-02-03 | 109 | 2027-03-20 | fine | NONE |
| Securenook | $8,400 | 2027-02-03 | 109 | 2027-03-05 | fine | NONE |
| Formkiln | $4,800 | 2027-03-01 | 135 | 2027-03-31 | fine | NONE |
| Payloom | $15,600 | 2027-03-01 | 135 | 2027-04-30 | fine | NONE |
| Codepillar | $27,000 | 2027-03-11 | 145 | 2027-04-10 | fine | NONE |
| Voxdesk | $33,000 | 2027-03-11 | 145 | 2027-05-10 | fine | NONE |
| Calendrift | $3,600 | 2027-03-23 | 157 | 2027-04-22 | fine | NONE |
| Datanest | $96,000 | 2027-04-01 | 166 | 2027-06-30 | fine | NONE |
| Insightpine | $38,000 | 2027-04-16 | 181 | 2027-06-15 | fine | NONE |
| Pingmoss | $7,200 | 2027-05-02 | 197 | 2027-06-01 | fine | NONE |

### Top 10 priorities

Score is the middle of the saving range, times a status weight (act now 2.0, window closed 1.5, upcoming 1.0, fine 0.5), times 1.25 if auto-renew has no approved exception.

| Rank | Vendor | Status | Saving range a year | Score | Why |
|---|---|---|---|---|---|
| 1 | Cloudpebble | upcoming | $13,320 to $26,640 | 24,975 | notice deadline in 56 days; auto-renew with no approved exception; 46% of seats in use |
| 2 | Taskwave | act now | $6,150 to $12,300 | 23,062 | notice deadline in 4 days; auto-renew with no approved exception; overlaps with a cheaper tool |
| 3 | Meetly | act now | $3,180 to $6,360 | 11,925 | notice deadline in 14 days; auto-renew with no approved exception; 65% of seats in use |
| 4 | Boardwick | window closed | $2,700 to $5,400 | 7,594 | notice deadline passed 19 days ago, rolls over on 2026-11-12; auto-renew with no approved exception; overlaps with a cheaper tool |
| 5 | Designmint | upcoming | $3,795 to $7,590 | 7,116 | notice deadline in 81 days; auto-renew with no approved exception; 55% of seats in use |
| 6 | Hirestack | upcoming | $4,200 to $8,400 | 6,300 | renews in 83 days, no auto-renew; 52% of seats in use |
| 7 | Planhive | fine | $5,985 to $11,970 | 5,611 | notice deadline in 104 days; auto-renew with no approved exception; 56% of seats in use |
| 8 | Insightpine | fine | $4,400 to $8,800 | 4,125 | notice deadline in 181 days; auto-renew with no approved exception; 69% of seats in use |
| 9 | Chatharbor | upcoming | $1,140 to $2,280 | 2,138 | notice deadline in 50 days; auto-renew with no approved exception; 85% of seats in use |
| 10 | Voxdesk | fine | $1,980 to $3,960 | 1,856 | notice deadline in 145 days; auto-renew with no approved exception; 80% of seats in use |

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
data/             vendors.csv and intel_fixtures/
examples/         committed sample outputs
tests/            pytest
docs/             how the numbers work, the verifier, live mode
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
