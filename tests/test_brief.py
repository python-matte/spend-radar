from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from spend_radar.brief import UNVERIFIED_HEADING, build_brief, build_claims_from_rules, verify_brief
from spend_radar.intel import FixtureProvider, collect_intel
from spend_radar.loader import find_vendor


def _bundle(vendors, analysis, name):
    vendor = find_vendor(vendors, name)
    return vendor, collect_intel(vendor, vendors, analysis, FixtureProvider())


def test_rule_based_brief_passes_its_own_verifier_for_every_vendor(vendors, analysis):
    for v in vendors:
        vendor, bundle = _bundle(vendors, analysis, v.vendor)
        claims = build_claims_from_rules(vendor, vendors, analysis, bundle)
        result = verify_brief(claims, bundle)
        assert result.ok, (v.vendor, [f.reasons for f in result.flagged])


def test_brief_has_all_seven_sections_and_the_unverified_heading(vendors, analysis, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    vendor, bundle = _bundle(vendors, analysis, "Taskwave")
    result = build_brief(vendor, vendors, analysis, bundle)
    for n in range(1, 8):
        assert f"## {n}. " in result.markdown
    assert f"## {UNVERIFIED_HEADING}" in result.markdown
    assert result.drafted_by == "rule-based template"


def test_closed_window_brief_leads_with_a_request_for_relief(vendors, analysis):
    vendor, bundle = _bundle(vendors, analysis, "Boardwick")
    claims = build_claims_from_rules(vendor, vendors, analysis, bundle)
    assert "released from the rollover" in claims.asks[0].text
    assert "not realistic this cycle" in claims.alternatives[-1].text


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.model = None
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.model = kwargs["model"]
        block = SimpleNamespace(type="text", text=self.payload)
        return SimpleNamespace(content=[block])


def test_model_draft_with_a_fabricated_claim_is_flagged_under_the_heading(vendors, analysis):
    vendor, bundle = _bundle(vendors, analysis, "Taskwave")
    payload = json.dumps(
        {
            "leverage": [
                {
                    "text": "Taskwave will cut its price by 40%.",
                    "evidence_id": "taskwave-sit-2",
                    "quote": "Taskwave promised a 40% price cut.",
                }
            ],
            "asks": [
                {
                    "text": "Remove auto-renew.",
                    "evidence_id": "taskwave-our-4",
                    "quote": "Auto-renew is on and no exception is approved.",
                }
            ],
        }
    )
    result = build_brief(vendor, vendors, analysis, bundle, client=FakeLLM(payload))
    assert not result.verification.ok
    head, tail = result.markdown.split(f"## {UNVERIFIED_HEADING}")
    assert "Taskwave will cut its price by 40%." in tail
    assert "Taskwave will cut its price by 40%." not in head
    assert "Remove auto-renew." in head


def test_model_name_comes_from_the_environment(vendors, analysis, monkeypatch):
    monkeypatch.setenv("SPEND_RADAR_MODEL", "my-test-model")
    vendor, bundle = _bundle(vendors, analysis, "Taskwave")
    fake = FakeLLM("{}")
    build_brief(vendor, vendors, analysis, bundle, client=fake)
    assert fake.model == "my-test-model"


def test_bad_model_json_falls_back_to_the_template(vendors, analysis):
    vendor, bundle = _bundle(vendors, analysis, "Taskwave")
    result = build_brief(vendor, vendors, analysis, bundle, client=FakeLLM("not json"))
    assert result.drafted_by == "rule-based template"
    assert result.verification.ok
    assert any("model draft failed" in n for n in result.notes)


@pytest.mark.parametrize("name", ["Taskwave", "Meetly", "Datanest"])
def test_no_key_means_template(vendors, analysis, monkeypatch, name):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    vendor, bundle = _bundle(vendors, analysis, name)
    assert build_brief(vendor, vendors, analysis, bundle).drafted_by == "rule-based template"
