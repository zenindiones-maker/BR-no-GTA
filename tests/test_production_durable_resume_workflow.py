from pathlib import Path


def test_production_continuation_runs_after_intermediate_failure():
    text=Path(
        ".github/workflows/real-multi-agent-production.yml"
    ).read_text(encoding="utf-8")
    block=text.split(
        "- name: Continue non-terminal durable mission",1
    )[1]
    assert "if: ${{ always() && !cancelled() }}" in block
    assert "!cancelled() && success()" not in block


def test_production_replan_is_transported_not_print_only():
    text=Path(
        ".github/workflows/real-multi-agent-production.yml"
    ).read_text(encoding="utf-8")
    block=text.split(
        "- name: Continue non-terminal durable mission",1
    )[1]
    assert "continuation_transition=" in block
    assert "continuation_strategy=" in block
    assert "continuation_route_id=" in block
    assert "continuation_authority_schema=" in block
    assert "checkpoint_artifact_digest=" in block
    assert "REPLAN_TRANSITION_EMITTED=PASS" in block
    assert "BLIND_RETRY_FORBIDDEN=PASS" in block
    assert "NORMAL_EXECUTE_DISPATCH=FORBIDDEN" not in block


def test_successor_requires_typed_continuation_contract():
    text=Path(
        ".github/workflows/real-multi-agent-production.yml"
    ).read_text(encoding="utf-8")
    assert "ContinuationAuthorization/v1" in text
    assert "BR_CONTINUATION_TRANSITION" in text
    assert "BR_CONTINUATION_STRATEGY" in text
    assert "BR_CONTINUATION_ROUTE_ID" in text
    assert "BR_EXPECTED_CHECKPOINT_DIGEST" in text
