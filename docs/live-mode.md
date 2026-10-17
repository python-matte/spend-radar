# Live mode

Live mode is off by default. Add `--live` to `intel` or `brief` to turn it on.

```bash
spend-radar intel Taskwave --live
spend-radar brief Taskwave --live --pricing-url https://example.com/pricing
```

## What it reads

- Google News RSS for the vendor name.
- The vendor's public pricing page, only if you give a URL with `--pricing-url`.

It does not search for competitors. The competitors bucket stays empty in live mode unless fixtures fill it.

## Rules it follows

- **robots.txt.** It reads robots.txt for each site first. If the rules say no, or it cannot read them, it does not fetch.
- **User agent.** It says who it is: `spend-radar/0.1`, with a short description.
- **Rate limit.** At least 2 seconds between requests.
- **Cache.** Results are cached on disk for 24 hours in `.spend_radar_cache/`. Change the folder with `SPEND_RADAR_CACHE_DIR`.
- **No logins or paywalls.** A 401, 402 or 403 response, or a redirect to a login page, is skipped.
- **Small data only.** It keeps a headline, a link, a date and a snippet of up to 200 characters. It never stores an article. For a pricing page it keeps up to five short lines that contain a price.
- **Prices.** If no price is on the page, the brief says "unknown, ask for a quote". It never estimates one.

## If it fails

If live collection returns nothing, for example because you are offline, the tool falls back to fixtures and says so in the notes. In this repo the fixtures are invented SAMPLE items.

## Honest note

The live provider is tested with fake HTTP clients. I did not run it against the real network while building this.
