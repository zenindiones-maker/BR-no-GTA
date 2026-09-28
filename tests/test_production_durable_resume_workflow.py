from pathlib import Path


def test_production_continuation_runs_after_intermediate_failure():
    text=Path(
        ".github/workflows/real-multi-agent-production.yml"
    ).read_text(encoding="utf-8")
    block=text.split(
        "- name: Continue non-terminal durable mission",1
    )[1]
    assert (
        "if: ${{ always() && !cancelled() && "
        "steps.durable_checkpoint.outcome == 'success' }}"
        in block
    )
    assert "!cancelled() && success()" not in block
    assert "steps.durable_checkpoint.outcome" in block


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



def test_nonterminal_continuation_requires_canonical_checkpoint_preparation():
    text=Path(
        ".github/workflows/real-multi-agent-production.yml"
    ).read_text(encoding="utf-8")
    prepare=text.split(
        "- name: Prepare governed non-terminal durable checkpoint",1
    )[1].split(
        "- name: Continue non-terminal durable mission",1
    )[0]
    continuation=text.split(
        "- name: Continue non-terminal durable mission",1
    )[1]
    assert "id: durable_checkpoint" in prepare
    assert "always() && !cancelled()" in prepare
    assert (
        "steps.durable_checkpoint.outcome == 'success'"
        in continuation
    )
    assert "success()" not in continuation


def test_file_driven_resume_exports_stable_durable_mission_key():
    text=Path(
        ".github/workflows/real-multi-agent-production.yml"
    ).read_text(encoding="utf-8")
    assert "BR_DURABLE_MISSION_KEY:" in text
    assert '"BR_DURABLE_MISSION_KEY": mission' in text
