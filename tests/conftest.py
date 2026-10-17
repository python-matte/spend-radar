from __future__ import annotations

import pytest

from spend_radar import core_logic as cl
from spend_radar.intel import FixtureProvider, collect_intel
from spend_radar.loader import AS_OF, find_vendor, load_vendors


@pytest.fixture(scope="session")
def vendors():
    return load_vendors()


@pytest.fixture(scope="session")
def analysis(vendors):
    return cl.analyze(vendors, AS_OF)


@pytest.fixture(scope="session")
def taskwave_bundle(vendors, analysis):
    vendor = find_vendor(vendors, "Taskwave")
    return collect_intel(vendor, vendors, analysis, FixtureProvider())
