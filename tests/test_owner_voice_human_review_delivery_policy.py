from __future__ import annotations

import pytest

from app.services.owner_voice_human_review_delivery_policy_service import (
    build_human_review_delivery_decision,
)


@pytest.mark.parametrize(
    ("identity_gate","content_gate"),
    [
        ("FAIL","PASS"),
        ("PASS","FAIL"),
        ("FAIL","FAIL"),
        ("PASS","PASS"),
    ],
)
def test_generated_candidate_is_always_deliverable_for_human_review(
    identity_gate:str,
    content_gate:str,
):
    decision=build_human_review_delivery_decision(
        identity_gate=identity_gate,
        content_audio_prescreen=content_gate,
    )
    assert decision["audition_delivery_eligible"] is True
    assert decision["human_review_required"] is True
    assert decision["human_review"]=="PENDING"
    assert decision["runtime_activation"] is False
    assert decision["automatic_gates_passed"] is (
        identity_gate=="PASS" and content_gate=="PASS"
    )


def test_invalid_gate_status_fails_closed():
    with pytest.raises(ValueError,match="AUTOMATIC_GATE_STATUS_INVALID"):
        build_human_review_delivery_decision(
            identity_gate="UNKNOWN",
            content_audio_prescreen="PASS",
        )
