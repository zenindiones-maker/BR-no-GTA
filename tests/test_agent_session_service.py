from app.services.agent_session_service import AgentSessionRuntime


def _session(tmp_path):
    return AgentSessionRuntime(
        artifact_dir=tmp_path,
        mission_id="mission-a",
        task_id="task-02",
        capability_id="addy:api-and-interface-design",
        agent_id="addy",
        skill_id="api-and-interface-design",
        functional_role="EVIDENCE",
        execution_kind="SEMANTIC_REASONER",
        allowed_tools=("artifact.evidence.reuse",),
        input_artifact_refs=("artifact:incident.json",),
        max_agent_turns=4,
        max_tool_calls=4,
        max_provider_calls=8,
        max_context_chars=15000,
        max_wall_clock_seconds=300,
    )


def test_provider_call_count_matches_real_external_calls(tmp_path):
    session = _session(tmp_path)
    session.record_provider_result({
        "provider_attempts": [
            {
                "attempt_id": "attempt-turn-1",
                "provider_id": "provider-a",
                "model_id": "model-a",
                "routing_id": "route-a",
                "status": "EXECUTED",
            },
            {
                "attempt_id": "attempt-turn-2",
                "provider_id": "provider-a",
                "model_id": "model-a",
                "routing_id": "route-a",
                "status": "EXECUTED",
            },
        ]
    })
    assert session.provider_recovery_state()["PROVIDER_CALL_COUNT"] == 2


def test_successful_pair_not_marked_exhausted(tmp_path):
    session = _session(tmp_path)
    session.record_provider_result({
        "provider_attempts": [{
            "attempt_id": "attempt-success",
            "provider_id": "provider-a",
            "model_id": "model-a",
            "routing_id": "route-a",
            "status": "EXECUTED",
        }]
    })
    recovery = session.provider_recovery_state()
    assert len(recovery["ATTEMPTED_PROVIDER_MODEL_PAIRS"]) == 1
    assert recovery["EXHAUSTED_PROVIDER_MODEL_PAIRS"] == []
    assert recovery["RECOVERY_STRATEGY"] is None


def test_same_agent_session_preserved_after_tool_result(tmp_path):
    session = _session(tmp_path)
    identity = session.agent_instance_id
    session.record_tool_request({
        "request_id": "request-1",
        "tool_or_capability_id": "artifact.evidence.reuse",
    })
    session.record_tool_result({
        "request_id": "request-1",
        "tool_id": "artifact.evidence.reuse",
        "operation": "read",
        "authorization_id": "auth-1",
        "status": "EXECUTED",
        "output_refs": ["artifact:tool-results/request-1.json"],
        "content_sha256": "c" * 64,
    })
    restored = _session(tmp_path)
    assert restored.restored is True
    assert restored.agent_instance_id == identity
    assert restored.state["TOOL_EXECUTIONS"][0]["request_id"] == "request-1"


def test_provider_domain_replay_prefers_provider_level_replan(tmp_path):
    session = _session(tmp_path)
    session.fail(
        failure_class="CapabilityReturnedFailure",
        evidence={
            "failure_domain_classification": {
                "schema": "FailureDomainClassification/v1",
                "provider_id": "provider-a",
                "scope": "PROVIDER_LOCAL",
                "provider_ejected": True,
                "provider_circuit": {"to_state": "OPEN"},
            },
            "provider_attempts": [
                {
                    "attempt_id": "a1",
                    "provider_id": "provider-a",
                    "model_id": "model-a",
                    "routing_id": "route-a",
                    "status": "FAILED",
                    "failure_class": "TRANSIENT_PROVIDER_HTTP_5XX",
                },
                {
                    "attempt_id": "b1",
                    "provider_id": "provider-a",
                    "model_id": "model-b",
                    "routing_id": "route-b",
                    "status": "FAILED",
                    "failure_class": "TRANSIENT_PROVIDER_TIMEOUT",
                },
            ],
        },
        turn_consumed=True,
    )
    restored = _session(tmp_path)
    recovery = restored.provider_recovery_state()
    assert recovery["RECOVERY_STRATEGY"] == "PROVIDER_LEVEL_REPLAN"
    assert recovery["TEMPORARILY_EJECTED_PROVIDER_IDS"] == ["provider-a"]
    assert recovery["PROVIDER_CIRCUIT_STATES"]["provider-a"] == "OPEN"
