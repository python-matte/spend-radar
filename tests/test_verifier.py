"""The verifier is the part that matters most. These tests pin down what it must reject."""

from __future__ import annotations

from spend_radar.brief import verify_brief
from spend_radar.schemas import BriefClaims, Claim


def find_item(bundle, needle):
    return next(i for i in bundle.items if needle in i.snippet)


def test_valid_claim_passes(taskwave_bundle):
    item = find_item(taskwave_bundle, "Kanbrook lists its Business plan")
    claim = Claim(
        text="A competitor lists its plan at $16 per seat per month.",
        evidence_id=item.id,
        quote="Kanbrook lists its Business plan at $16 per seat per month billed annually.",
    )
    result = verify_brief(BriefClaims(leverage=[claim]), taskwave_bundle)
    assert result.ok
    assert result.verified.leverage == [claim]


def test_fabricated_quote_is_rejected(taskwave_bundle):
    item = find_item(taskwave_bundle, "Tasksprout offers")
    claim = Claim(
        text="Tasksprout will match any price we are paying.",
        evidence_id=item.id,
        quote="Tasksprout will match any price a customer is paying today.",
    )
    result = verify_brief(BriefClaims(leverage=[claim]), taskwave_bundle)
    assert not result.ok
    assert result.verified.leverage == []
    assert any("quote" in reason for reason in result.flagged[0].reasons)


def test_invented_price_is_rejected(taskwave_bundle):
    item = find_item(taskwave_bundle, "Kanbrook lists its Business plan")
    claim = Claim(
        text="Kanbrook lists its Business plan at $9 per seat per month.",
        evidence_id=item.id,
        quote="Kanbrook lists its Business plan at $16 per seat per month billed annually.",
    )
    result = verify_brief(BriefClaims(leverage=[claim]), taskwave_bundle)
    assert not result.ok
    assert any("$9" in reason for reason in result.flagged[0].reasons)


def test_unknown_evidence_id_is_rejected(taskwave_bundle):
    claim = Claim(
        text="The vendor was fined last year.",
        evidence_id="taskwave-sit-99",
        quote="The vendor was fined last year.",
    )
    result = verify_brief(BriefClaims(asks=[claim]), taskwave_bundle)
    assert not result.ok
    assert any("evidence_id" in reason for reason in result.flagged[0].reasons)


def test_missing_quote_is_rejected(taskwave_bundle):
    item = find_item(taskwave_bundle, "Tasksprout offers")
    claim = Claim(text="They have a switching offer.", evidence_id=item.id, quote="")
    result = verify_brief(BriefClaims(questions=[claim]), taskwave_bundle)
    assert not result.ok
