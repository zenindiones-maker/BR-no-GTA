from app.services.harness_durable_execution_service import HarnessDurableExecutionService


def _result(task_id="research", mission_id="mission-1"):
    return {
        "mission_id": mission_id,
        "task_id": task_id,
        "capability_id": "gta6.research",
        "status": "COMPLETED",
        "task_result_ref": f"artifact:task-results/{task_id}.json",
        "task_result_sha256": "abc123",
        "result": {"topic": "Vice City", "claims": [{"statement": "grounded"}]},
        "producer_state_version": 3,
    }


def test_worker_restart_materializes_completed_predecessor_without_reexecution(tmp_path):
    service = HarnessDurableExecutionService(
        mission_id="mission-1", state_version=4, artifact_dir=tmp_path
    )
    ctx = service.materialize(
        consumer_task_id="fact-check",
        required_task_ids=("research",),
        task_results={"research": (_result(),)},
    )
    assert ctx.status == "READY"
    assert ctx.reused_task_ids == ("research",)
    assert ctx.dependencies[0]["result"]["claims"][0]["statement"] == "grounded"
    assert service.persist_context(ctx).exists()


def test_materialization_is_deterministic(tmp_path):
    service = HarnessDurableExecutionService(
        mission_id="mission-1", state_version=4, artifact_dir=tmp_path
    )
    kwargs = dict(
        consumer_task_id="fact-check",
        required_task_ids=("research",),
        task_results={"research": (_result(),)},
    )
    assert service.materialize(**kwargs).context_digest == service.materialize(**kwargs).context_digest


def test_missing_dependency_fails_closed(tmp_path):
    service = HarnessDurableExecutionService(
        mission_id="mission-1", state_version=4, artifact_dir=tmp_path
    )
    ctx = service.materialize(
        consumer_task_id="fact-check",
        required_task_ids=("research",),
        task_results={},
    )
    assert ctx.status == "MISSING_DURABLE_DEPENDENCY"


def test_wrong_mission_fails_closed(tmp_path):
    service = HarnessDurableExecutionService(
        mission_id="mission-1", state_version=4, artifact_dir=tmp_path
    )
    ctx = service.materialize(
        consumer_task_id="fact-check",
        required_task_ids=("research",),
        task_results={"research": (_result(mission_id="mission-other"),)},
    )
    assert ctx.status == "CONTRADICTORY_LINEAGE"


def test_transport_failure_does_not_consume_task_or_strategy_budget():
    q = HarnessDurableExecutionService.classify_progress_quantum(
        state_version_before=8,
        state_version_after=8,
        failure_signature="worker-lost",
        strategy_signature="research:v1",
        transport_failure=True,
    )
    assert q["consumes_task_retry"] is False
    assert q["consumes_strategy_attempt"] is False
    assert q["no_progress"] is True


def test_real_task_attempt_consumes_task_retry_not_transport():
    q = HarnessDurableExecutionService.classify_progress_quantum(
        state_version_before=8,
        state_version_after=8,
        executed_task_ids=("fact-check",),
        failure_signature="provider-transient",
        strategy_signature="fact-check:v1",
    )
    assert q["consumes_task_retry"] is True
    assert q["consumes_strategy_attempt"] is True


def test_strategy_exhaustion_with_alternative_replans():
    assert HarnessDurableExecutionService.continuation_eligibility(
        objective_satisfied=False,
        strategy_budget_exhausted=True,
        replan_available=True,
    ) == "REPLAN_REQUIRED"


def test_continuation_count_is_not_a_semantic_terminal_input():
    # There is deliberately no continuation_count argument. Transport/redrive
    # observability cannot decide mission completion.
    assert HarnessDurableExecutionService.continuation_eligibility(
        objective_satisfied=False,
        runnable_work=True,
    ) == "CONTINUATION_REQUIRED"


def test_objective_satisfaction_is_explicit_terminal_success():
    assert HarnessDurableExecutionService.continuation_eligibility(
        objective_satisfied=True,
        runnable_work=True,
    ) == "CONTINUATION_NOT_REQUIRED_OBJECTIVE_SATISFIED"


def test_human_continue_required_for_internal_failure_is_zero():
    assert HarnessDurableExecutionService.continuation_eligibility(
        objective_satisfied=False,
        recoverable_work=True,
    ) == "CONTINUATION_REQUIRED"
