# The verifier

The brief is only useful if I can check it. `verify_brief()` in `src/spend_radar/brief.py` does that check.

## What a claim is

Sections 2 to 6 of a brief are lists of claims. Each claim has three fields:

- `text`: what we say
- `evidence_id`: the evidence item it rests on
- `quote`: words copied from that item

Evidence comes from two places. Items from a provider (fixtures or live) are tagged with source and date. Items about our own contract, usage and spend are built from `vendors.csv` and the analysis, so a claim about our data is checked the same way.

## What gets flagged

A claim is flagged if any of these is true:

- it has no `evidence_id`, or the id is not in the stored evidence
- it has no quote, or the quote is under 10 characters
- the quote is not found word for word in that item's title or snippet (white space is ignored, case is not)
- it contains a number that does not appear in our data or in any evidence item
- it contains a date that does not appear in our data or in any evidence item

Numbers are checked by type. A claim with `$9` needs a `$9` somewhere in the evidence. A `9%` in the evidence does not count. This stops an invented price from slipping through on a coincidence.

One number is allowed without evidence: the uplift cap we ask for (3%). It is our own target, set in `core_logic.py`.

## What happens to a flagged claim

It is removed from sections 2 to 6 and listed under **Unverified, check before using**, with the reasons. Nothing is dropped silently. The heading always appears. If nothing was flagged it says so.

## What it does not check

- It checks that words and numbers come from the evidence. It does not check that the evidence is true.
- It does not check that a claim means what the quote means. A person has to read it.
- Fixture evidence is invented. Live evidence is a headline and a short snippet, so read the source before you quote it.
