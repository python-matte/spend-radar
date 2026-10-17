"""Docs, fixtures and committed examples follow the writing rules."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BANNED = ["—", "seamless", "robust", "powerful", "streamline", "delve", "not just"]
# "Leverage points" is a section name the brief must have. As a verb it is banned.
VERB_LEVERAGE = re.compile(r"\bleverag(?:e|ed|es|ing)\b(?! points?\b)", re.IGNORECASE)


def _files():
    for pattern in ("*.md", "docs/**/*.md", "examples/**/*", "data/**/*.json", "data/*.csv"):
        yield from (p for p in ROOT.glob(pattern) if p.is_file())


def test_no_banned_words_or_em_dashes():
    problems = []
    for path in _files():
        text = path.read_text(encoding="utf-8")
        low = text.lower()
        problems += [f"{path.name}: {w!r}" for w in BANNED if w in low]
        if VERB_LEVERAGE.search(text):
            problems.append(f"{path.name}: leverage used as a verb")
    assert not problems, problems
