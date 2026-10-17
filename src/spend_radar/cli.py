"""Command line: analyze, intel <vendor>, brief <vendor>, report."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from . import core_logic as cl
from .brief import build_brief
from .intel import (
    FixtureProvider,
    NewsProvider,
    build_live_provider,
    collect_intel,
    render_intel_markdown,
)
from .loader import AS_OF, default_data_dir, find_vendor, load_vendors
from .report import render_analyze_text, render_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spend-radar",
        description="Find where software spend leaks and write negotiation briefs you can check.",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data", type=Path, help="vendors CSV (default: data/vendors.csv)")
    common.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=AS_OF,
        help=f"as-of date, YYYY-MM-DD (default: {AS_OF.isoformat()})",
    )
    common.add_argument("--out", type=Path, help="write to this file instead of the screen")

    sub = parser.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", parents=[common], help="find the leaks and rank them")
    a.add_argument("--json", action="store_true", help="print the full analysis as JSON")

    for name, help_text in (
        ("intel", "collect evidence for one vendor"),
        ("brief", "write a negotiation brief for one vendor"),
    ):
        p = sub.add_parser(name, parents=[common], help=help_text)
        p.add_argument("vendor")
        p.add_argument(
            "--live",
            action="store_true",
            help="read Google News RSS (and a pricing page if given). Off by default.",
        )
        p.add_argument("--pricing-url", help="public pricing page, used only with --live")
        if name == "brief":
            p.add_argument(
                "--no-llm", action="store_true", help="use the rule-based template even with a key"
            )

    sub.add_parser("report", parents=[common], help="write the full portfolio report")
    return parser


def _provider(live: bool) -> NewsProvider:
    if live:
        print(
            "Live mode: public headlines and an optional public pricing page only. "
            "robots.txt is honoured, requests are rate limited, results are cached 24 hours.",
            file=sys.stderr,
        )
        return build_live_provider(fallback=FixtureProvider())
    return FixtureProvider()


def _emit(text: str, out: Path | None) -> None:
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"Wrote {out}", file=sys.stderr)
    else:
        sys.stdout.write(text)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        vendors = load_vendors(args.data)
    except (OSError, ValueError) as exc:
        print(f"Could not read the vendor list: {exc}", file=sys.stderr)
        return 2
    analysis = cl.analyze(vendors, args.as_of)

    if args.command == "analyze":
        text = (
            analysis.model_dump_json(indent=2) + "\n"
            if args.json
            else render_analyze_text(vendors, analysis)
        )
        _emit(text, args.out)
        return 0

    if args.command == "report":
        sample = args.data is None or args.data.resolve() == (default_data_dir() / "vendors.csv")
        _emit(render_report(vendors, analysis, sample=sample), args.out)
        return 0

    try:
        vendor = find_vendor(vendors, args.vendor)
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 2
    bundle = collect_intel(
        vendor, vendors, analysis, _provider(args.live), pricing_url=args.pricing_url
    )
    if args.command == "intel":
        _emit(render_intel_markdown(bundle), args.out)
        return 0

    result = build_brief(vendor, vendors, analysis, bundle, use_llm=not args.no_llm)
    _emit(result.markdown, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
