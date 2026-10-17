# The monthly run

This page shows how I would run spend-radar once a month and where each piece would live. I have not turned any of it on. Nothing in this repo sends a message unless you add `--send`, and the sample config only holds placeholder addresses.

## What one run does

```bash
spend-radar digest --config config/notify.json
```

1. Reads the vendor list and works out the decisions.
2. Loads last month's snapshot, if there is one, and works out what changed.
3. Builds one email and one Slack message per recipient.
4. Writes them to a folder so a person can read them first. This is a dry run.
5. Saves this month's snapshot for next time.

With `--send` it sends the messages instead of only writing them.

## Who gets what

`config/notify.example.json` maps each `owner_team` in the vendor list to a contact.

- **The spend owner** gets everything: the recommendation, every decision, what changed, the auto-renew watch, and `dashboard.html` as an attachment. Teams with no contact in the config are named in this message so nobody is missed.
- **Each team lead** gets only their own vendors: their decisions for the next 90 days, their spend, and what changed for them. A team with nothing due gets no message.

A message has a subject like `[Spend radar] October 2026: 3 decisions due now, $12,030 to $24,060 at stake`. The Slack version has the same content as blocks, with the recommendation first.

## What changed since last month

Each run saves a small JSON snapshot to `.spend_radar_state/`. The next run compares against the latest earlier one and reports:

- notice windows that closed
- contracts that are now due
- decisions still open from last month
- renewals, including when auto-renew was removed
- vendors added or removed

The first run has nothing to compare with, and says so. The files in `examples/` were made by running with `--as-of 2026-09-17` first, then with the default date. The "last month" is simulated that way. It is not real history.

## Secrets

The config file holds names of environment variables, never the secrets.

| Variable | Used for |
|---|---|
| `SPEND_RADAR_SMTP_HOST`, `SPEND_RADAR_SMTP_USER`, `SPEND_RADAR_SMTP_PASSWORD` | email login |
| `SPEND_RADAR_SMTP_PORT` | optional, default 587 |
| `SPEND_RADAR_FROM` | the From address |
| the names in `slack_webhook_env` | one Slack incoming webhook per channel |

## Guards on sending

- Dry run is the default. You must pass `--send`.
- Before sending anything, it checks every address and every variable. If one thing is missing, it sends nothing and lists the problems.
- It refuses `example.com`, `example.org` and `example.net` addresses.

## The schedule

Two ways I would schedule it. Neither is switched on.

**On a machine I control.** One line in `crontab`, running at 07:00 on the first of each month:

```cron
0 7 1 * * cd /path/to/spend-radar && .venv/bin/spend-radar digest --config config/notify.json --send >> digest.log 2>&1
```

**On GitHub Actions.** `docs/examples/monthly-digest.yml` is a ready workflow. It sits in `docs/`, not in `.github/workflows/`, so GitHub ignores it. Moving it would need a remote repository, which I have not made.

## Where the visuals live

`spend-radar dashboard` writes one HTML file. It has no scripts and makes no outside requests, so it opens from a file and survives being attached to an email. In a real setup I would also host the latest copy somewhere the team can reach, and link to it from the Slack message.

## What I would change before using it on real data

- Replace the CSV with an export from the finance or procurement system.
- Keep the snapshots in storage that does not expire.
- Have the spend owner read the dry-run output for the first few months before turning on `--send`.
- Store secrets in a secrets manager.
