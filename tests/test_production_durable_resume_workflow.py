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



def test_checkpoint_reconciliation_uses_completed_editorial_progress():
    text=Path(
        ".github/workflows/real-multi-agent-production.yml"
    ).read_text(encoding="utf-8")
    assert "editorial_progress_snapshot(" in text
    assert "COMPLETED_RESULTS_PRESERVED=PASS" in text
    assert "DURABLE_EDITORIAL_PROGRESS_RECONCILED=PASS" in text
    assert "EDITORIAL_SUPPORTED_DURATION_MINUTES=" in text
    assert (
        'if row.get("status") != "PARTIAL_FAILED": continue'
        not in text
    )



def test_successor_identity_is_logical_not_physical_run_id():
    text=Path(
        ".github/workflows/real-multi-agent-production.yml"
    ).read_text(encoding="utf-8")
    assert (
        "run-name: Real Multi-Agent Production · "
        "${{ inputs.continuation_id || github.run_id }}"
        in text
    )
    continuation=text.split(
        "- name: Continue non-terminal durable mission",1
    )[1]
    assert "successor_intent_id=" in continuation
    assert "effective_input_digest=" in continuation
    assert "DUPLICATE_SUCCESSOR_INTENT_DEDUPED=PASS" in continuation
    assert "SUCCESSOR_DISPATCH_IDEMPOTENT=PASS" in continuation
    assert "successor_dispatch_decision" in continuation


def test_execution_failure_is_persisted_before_nonterminal_reconciliation():
    text=Path(
        ".github/workflows/real-multi-agent-production.yml"
    ).read_text(encoding="utf-8")
    execute=text.split(
        "- name: Execute natural goal through Harness-selected agents",1
    )[1].split(
        "- name: Deliver human-readable editorial package to Telegram",1
    )[0]
    assert "execution-failure.json" in execute
    assert "ProductionExecutionFailure/v1" in execute
    assert "physical_attempt_id" in execute
    assert "PRODUCTION_EXECUTION_FAILURE_CAPTURED=PASS" in execute


def test_successor_intent_is_persisted_before_checkpoint_upload():
    text=Path(
        ".github/workflows/real-multi-agent-production.yml"
    ).read_text(encoding="utf-8")
    prepare=text.index(
        "- name: Prepare governed non-terminal durable checkpoint"
    )
    upload=text.index("- name: Upload complete real production evidence")
    assert prepare < upload
    between=text[prepare:upload]
    assert "successor-intent.json" in between
    assert "SUCCESSOR_INTENT_PERSISTED=PASS" in between


def test_logical_continuation_claim_fails_closed_for_second_writer():
    text=Path(
        ".github/workflows/real-multi-agent-production.yml"
    ).read_text(encoding="utf-8")
    block=text.split(
        "- name: Claim logical continuation exactly once",1
    )[1].split("- uses: actions/setup-python@v5",1)[0]
    assert "SECOND_WRITER_FAILS_CLOSED=PASS" in block
    assert "continuation-claim.json" in block
    assert "ONE_ACTIVE_WRITER_PER_MISSION=PASS" in block


def test_final_reconciliation_proves_monotonic_and_effective_input_contracts():
    text=Path(
        ".github/workflows/real-multi-agent-production.yml"
    ).read_text(encoding="utf-8")
    for marker in (
        "INITIAL_STATE_VERSION=",
        "REHYDRATED_COMPLETED_TASKS=",
        "INITIAL_SUPPORTED_DURATION=",
        "EFFECTIVE_INPUT_DIGEST=",
        "PROGRESS_DELTA=",
        "MONOTONIC_MISSION_STATE=PASS",
        "MONOTONIC_SUPPORTED_DURATION=PASS",
        "COMPLETED_RESULT_PRESERVED=PASS",
        "OLD_PARTIAL_DOES_NOT_OVERRIDE_COMPLETED=PASS",
        "EDITORIAL_TASK_NOT_REOPENED_WITHOUT_INVALIDATION=PASS",
    ):
        assert marker in text



def test_production_report_uses_semantic_progress_contract_and_concrete_requirements():
    text=Path(
        ".github/workflows/real-multi-agent-production.yml"
    ).read_text(encoding="utf-8")
    block=text.split(
        "- name: Build final operational production report",1
    )[1].split(
        "- name: Prepare governed non-terminal durable checkpoint",1
    )[0]
    assert "build_production_progress_contract" in block
    assert 'artifact_created_digest=progress_contract[' in block
    assert 'task_result_identity=task_result_identity' in block
    assert 'resolved_requirements=resolved_requirements' in block
    assert 'effective_input_digest=effective_input_digest' in block
    assert 'route_identity=route_identity' in block
    assert 'physical_attempt_id=physical_attempt_id' in block
    assert "CONCRETE_REMAINING_REQUIREMENTS=PASS" in block
    assert block.count("CONTINUE_ORIGINAL_PRODUCTION")==1
    assert (
        'if "CONTINUE_ORIGINAL_PRODUCTION" not in remaining_requirements:'
        in block
    )


def test_rehydrate_logical_continuation_imports_regex_dependency():
    text=Path(
        ".github/workflows/real-multi-agent-production.yml"
    ).read_text(encoding="utf-8")
    block=text.split(
        "- name: Rehydrate durable mission checkpoint",1
    )[1].split("- name: Install production dependencies",1)[0]
    assert "import json, os, re" in block
    assert "re.fullmatch" in block


def test_logical_continuation_claim_allows_only_proven_pre_semantic_physical_retry():
    text=Path(
        ".github/workflows/real-multi-agent-production.yml"
    ).read_text(encoding="utf-8")
    block=text.split(
        "- name: Claim logical continuation exactly once",1
    )[1].split("- uses: actions/setup-python@v5",1)[0]
    assert "continuation_claim_decision" in block
    assert "retry-safe-runs.json" in block
    assert "Execute natural goal through Harness-selected agents" in block
    assert "Dispatch professional render" in block
    assert "Dispatch canonical YouTube PRIVATE HD review upload" in block
    assert "NONTERMINAL_SUCCESSOR_DISPATCHED=PASS" in block
    assert "DUPLICATE_SUCCESSOR_INTENT_DEDUPED=PASS" in block
    assert "PHYSICAL_RETRY_OF_RUN_ID=" in block
    assert "FAILED_PRE_SEMANTIC_ATTEMPT_REPLACED=PASS" in block


def test_physical_retry_safety_uses_canonical_dispatch_receipt_not_raw_log_grep():
    text=Path(
        ".github/workflows/real-multi-agent-production.yml"
    ).read_text(encoding="utf-8")
    block=text.split(
        "- name: Claim logical continuation exactly once",1
    )[1].split("- uses: actions/setup-python@v5",1)[0]
    assert "physical_attempt_retry_safe" in block
    assert "successor-dispatch-receipt.json" in block
    assert 'gh run view "$RID"' not in block
    assert "grep -Eq" not in block
