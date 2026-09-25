from app.services import harness_mission_execution_router as router


def test_execution_need_is_persisted_and_resolved_by_canonical_selector(tmp_path, monkeypatch):
    captured = {}

    def fake_select(requirement, *, context, used):
        captured["requirement"] = requirement
        captured["used"] = used
        return (
            "gta6.fact-check",
            True,
            ("bad.route:failure-memory",),
            {"selection_reason_codes": ["semantic-match", "healthy"]},
        )

    monkeypatch.setattr(router, "select_capability_for_requirement", fake_select)
    result = router.resolve_harness_execution_need(
        mission_plan={"mission_id": "mission-need-1"},
        need={
            "schema": "HarnessExecutionNeed/v1",
            "status": "NEEDS_CAPABILITY",
            "failure_class": "INSUFFICIENT_EVIDENCE",
            "semantic_requirement": "additional verified primary evidence for gaps",
            "missing_requirements": ["gap-a", "gap-b"],
            "produced_artifact_refs": ["artifact:partial-script"],
            "retryability": "REPLAN_REQUIRED",
            "replan_required": True,
            "causal_task_id": "script-task",
            "producer_selected_resolver": False,
        },
        planning_context={"mission_class": "GTA6_INTELLIGENCE"},
        artifact_dir=tmp_path,
        used_capability_ids={"script.generate"},
    )

    assert result["mission_state_update"]["decision"] == "REPLAN"
    assert result["mission_state_update"]["resume_scope"] == "MINIMAL_AFFECTED_SUBGRAPH"
    assert result["resolution"]["selected_capability_id"] == "gta6.fact-check"
    assert result["resolution"]["producer_selected_resolver"] is False
    assert captured["requirement"]["required_capability_description"] == (
        "additional verified primary evidence for gaps"
    )
    assert "gta6.research" not in repr(captured["requirement"])
    assert captured["used"] == {"script.generate"}
    assert list((tmp_path / "harness-execution-needs").glob("*.json"))


def test_execution_need_retry_does_not_resolve_new_capability(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("retry must not perform semantic replan")

    monkeypatch.setattr(router, "select_capability_for_requirement", forbidden)
    result = router.resolve_harness_execution_need(
        mission_plan={"mission_id": "mission-retry-1"},
        need={
            "schema": "HarnessExecutionNeed/v1",
            "status": "BLOCKED",
            "failure_class": "PROVIDER_TRANSIENT",
            "semantic_requirement": "same bounded operation",
            "missing_requirements": [],
            "produced_artifact_refs": [],
            "retryability": "RETRYABLE",
            "replan_required": False,
            "causal_task_id": "task-a",
            "producer_selected_resolver": False,
        },
        planning_context={"mission_class": "OPEN_SEMANTIC"},
        artifact_dir=tmp_path,
    )
    assert result["mission_state_update"]["decision"] == "RETRY"
    assert result["resolution"] is None
