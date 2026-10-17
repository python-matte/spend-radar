# How the numbers work

All the math is in `src/spend_radar/core_logic.py`. It has no file access, no network and no model calls. Every function takes the as-of date as an argument, so a run gives the same answer every time. The sample data uses 2026-10-17.

## Renewals

- **Notice deadline** is the renewal date minus `notice_days`.
- **Start negotiating by** is 120 days before the renewal date.
- **Status** for a contract on auto-renew uses days to the notice deadline:
  - act now: 0 to 30 days
  - upcoming: 31 to 90 days
  - fine: more than 90 days
  - window closed: the deadline has passed, so the contract rolls over
- A contract without auto-renew has nothing to roll over. Its status uses days to the renewal date instead.
- **Next cycle deadline** is the notice deadline for the term after this one. It is in the brief timeline so a closed window turns into a reminder.

## Auto-renew policy

My aim is no auto-renew on any contract. The `auto_renew` column says which contracts have it. The `auto_renew_approved_by` column records who approved a rare exception. A blank means nobody did.

- The report lists every auto-renew contract, soonest deadline first.
- Auto-renew with no approved exception gets a 1.25 factor in the priority score.
- A closed window is not marked down. It is a contract that will roll over, so it keeps a high weight.
- Removing auto-renew is the first ask in a brief, unless the window is closed. Then the first ask is a written request to be released from the rollover.

## Overlaps

Vendors are grouped by category. For each group with two or more vendors:

1. Cost per seat is annual cost divided by seats purchased.
2. The vendor with the lowest cost per seat is the target.
3. For every other vendor, the saving is its annual cost minus its active seats at the target rate. It is never below zero.
4. Low case is 50% of that total. High case is 100%.

The assumption is printed next to the number. It assumes the target vendor will sell the extra seats at its current rate. Only a written quote can confirm that.

## Unused seats

Only per-seat plans are counted. Dropping seats on a flat or usage plan does not lower the bill.

1. Keep 10% headroom: seats to keep = active seats x 1.1, rounded up.
2. Excess seats = seats purchased minus seats to keep, never below zero.
3. Price per seat = annual cost divided by seats purchased.
4. High case = excess x price. Low case = half of that.

## Priority score

For each vendor the saving is the larger of its unused-seat saving and its overlap saving, taken bound by bound. They describe the same money, so I do not add them.

`score = middle of the saving range x status weight x auto-renew factor`

| Status | Weight |
|---|---|
| act now | 2.0 |
| window closed | 1.5 |
| upcoming | 1.0 |
| fine | 0.5 |

The auto-renew factor is 1.25 when auto-renew has no approved exception, otherwise 1.0. The weights are named constants at the top of `core_logic.py`. The top 10 by score is the ranked list.

## Things this does not do

- It does not know your real prices. Cost per seat is a blunt average.
- It does not know migration cost or contract terms beyond the CSV.
- Savings in one category can overlap, so the portfolio total is a rough upper sketch.
