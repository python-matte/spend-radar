"""CSV loading. Kept out of core_logic so that module stays free of I/O."""

from __future__ import annotations

import csv
import os
from datetime import date
from pathlib import Path

from .schemas import Vendor

# Fixed so every run gives the same answer. Override with --as-of.
AS_OF = date(2026, 10, 17)


def default_data_dir() -> Path:
    env = os.environ.get("SPEND_RADAR_DATA_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2] / "data"


def load_vendors(path: Path | None = None) -> list[Vendor]:
    csv_path = path or default_data_dir() / "vendors.csv"
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return [Vendor.model_validate(row) for row in csv.DictReader(handle)]


def find_vendor(vendors: list[Vendor], name: str) -> Vendor:
    wanted = "".join(ch for ch in name.lower() if ch.isalnum())
    for v in vendors:
        if v.slug == wanted:
            return v
    known = ", ".join(sorted(v.vendor for v in vendors))
    raise KeyError(f"No vendor called {name!r}. Known vendors: {known}")
