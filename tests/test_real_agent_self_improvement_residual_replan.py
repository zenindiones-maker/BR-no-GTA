import json

import pytest

from app.services.agent_session_service import stable_agent_instance_id
from scripts.real_agent_self_improvement_mission import (
    apply_provider_reconciliation_checkpoint,
    apply_runtime_residual_replan,
)

def test_real_entrypoint_consumes_runtime_residual_replan(monkeypatch):
 monkeypatch.setenv("BR_RUNTIME_CAPABILITY_ELIGIBILITY_JSON",json.dumps({
  "agent-office.codex.readonly-analysis":{"eligible":True,"health_state":"HEALTHY","reason":"authenticated"},
  "addy:debugging-and-error-recovery":{"eligible":False,"health_state":"BLOCKED","reason":"semantic provider unavailable"}}))
 plan={"collaboration_plan":{"tasks":[
  {"task_id":"task-01","capability_id":"artifact.evidence.reuse","action":"DEVELOPMENT","objective":"evidence","dependencies":[],"input_refs":[],"expected_output":"IncidentEvidencePack/v1","task_class":"evidence","functional_role":"EVIDENCE","required_operations":["CAN_PRODUCE_ARTIFACT_REFS"],"risk_side_effect_class":"READ_ONLY","candidate_requirement":"NOT_APPLICABLE"},
  {"task_id":"task-02","capability_id":"addy:debugging-and-error-recovery","action":"DEVELOPMENT","objective":"diagnose","dependencies":["task-01"],"input_refs":[],"expected_output":"IncidentDiagnosisEvidence","task_class":"diagnosis","functional_role":"DIAGNOSIS","required_operations":["CAN_SEMANTIC_REASONING","CAN_CONSUME_ARTIFACT_REFS","CAN_PRODUCE_ARTIFACT_REFS"],"risk_side_effect_class":"READ_ONLY","candidate_requirement":"NOT_APPLICABLE","selected_agent_id":"addy-agent-skills"},
  {"task_id":"task-03","capability_id":"addy:debugging-and-error-recovery","action":"DEVELOPMENT","objective":"root","dependencies":["task-02"],"input_refs":[],"expected_output":"RootCauseEvidence","task_class":"root","functional_role":"ROOT_CAUSE","required_operations":["CAN_SEMANTIC_REASONING"],"risk_side_effect_class":"READ_ONLY","candidate_requirement":"NOT_APPLICABLE"}],
  "execution_levels":[["task-01"],["task-02"],["task-03"]]}}
 spec={"parent_task_id":"task-02","task_id":"task-02-semantic-diagnosis","functional_role":"DIAGNOSIS","task_class":"incident-diagnosis","required_operations":["CAN_SEMANTIC_REASONING","CAN_CONSUME_ARTIFACT_REFS","CAN_PRODUCE_ARTIFACT_REFS"],"required_input_artifact_schemas":["IncidentEvidencePack/v1"],"expected_output_schema":"IncidentDiagnosisEvidence/v1","side_effect_class":"READ_ONLY","mutation_requirement":"NOT_APPLICABLE","input_artifact_refs":["runtime/pack.json"],"forbidden_capabilities":[{"capability_id":"addy:debugging-and-error-recovery","reason":"provider unavailable"}]}
 revised,e=apply_runtime_residual_replan(plan,residual_spec=spec)
 assert e["ORIGINAL_TASK_CAPABILITY"]=="addy:debugging-and-error-recovery"
 assert e["RESIDUAL_REPLAN_PERFORMED"]=="PASS"
 assert e["RESIDUAL_SELECTED_CAPABILITY"]=="agent-office.codex.readonly-analysis"
 assert e["RESIDUAL_SELECTED_AGENT"]=="codex-readonly"
 assert e["ADDY_RUNTIME_INVOCATION_COUNT"]==0
 assert e["CODEX_RUNTIME_INVOCATION_COUNT"]==1
 tasks={x["task_id"]:x for x in revised["collaboration_plan"]["tasks"]}
 assert "task-02" not in tasks
 assert tasks["task-02-semantic-diagnosis"]["input_refs"]==["runtime/pack.json"]
 assert tasks["task-03"]["dependencies"]==["task-02-semantic-diagnosis"]


def test_provider_requeue_restores_exact_session_from_checkpoint_source(tmp_path):
    mission_id = "mission-a"
    task_id = "task-02-semantic-diagnosis"
    capability_id = "addy:debugging-and-error-recovery"
    agent_id = "addy-agent-skills"
    skill_id = "debugging-and-error-recovery"
    agent_instance_id = stable_agent_instance_id(
        mission_id=mission_id,
        task_id=task_id,
        capability_id=capability_id,
        agent_id=agent_id,
        skill_id=skill_id,
    )

    checkpoint_source = tmp_path / "checkpoint-source"
    source_runtime = checkpoint_source / "first-runtime"
    session_dir = source_runtime / "agent-sessions"
    session_dir.mkdir(parents=True)
    tool_dir = source_runtime / "tool-results"
    tool_dir.mkdir(parents=True)
    tool_ref = "artifact:tool-results/provider.json"
    tool_envelope = {
        "schema": "ToolResultEnvelope/v1",
        "mission_id": mission_id,
        "task_id": task_id,
        "content_sha256": "tool-hash",
    }
    (tool_dir / "provider.json").write_text(
        json.dumps(tool_envelope),
        encoding="utf-8",
    )
    session_state = {
        "schema": "AgentSession/v1",
        "AGENT_INSTANCE_ID": agent_instance_id,
        "MISSION_ID": mission_id,
        "TASK_ID": task_id,
        "CAPABILITY_ID": capability_id,
        "AGENT_ID": agent_id,
        "SKILL_ID": skill_id,
        "FUNCTIONAL_ROLE": "DIAGNOSIS",
        "EXECUTION_KIND": "SEMANTIC_REASONER",
        "ALLOWED_TOOLS": [],
        "INPUT_ARTIFACT_REFS": [],
        "MAX_AGENT_TURNS": 4,
        "MAX_TOOL_CALLS": 2,
        "MAX_PROVIDER_CALLS": 3,
        "MAX_CONTEXT": 20000,
        "MAX_WALL_CLOCK_SECONDS": 120,
        "MANDATORY_TOOL_REQUIREMENTS": [],
        "STATUS": "FAILED",
        "TURN_INDEX": 2,
        "TOOL_REQUESTS": [],
        "TOOL_EXECUTIONS": [{
            "request_id": "request-a",
            "tool_id": "provider",
            "operation": "generate",
            "status": "COMPLETED",
            "output_refs": [tool_ref],
            "content_sha256": "tool-hash",
        }],
        "PROVIDER_ATTEMPTS": [{
            "provider_id": "nvidia_nim",
            "model_id": "model-a",
            "status": "FAILED",
        }],
    }
    (session_dir / f"{task_id}-{agent_instance_id}.json").write_text(
        json.dumps(session_state),
        encoding="utf-8",
    )

    reconciliation_dir = tmp_path / "provider-reconciliation"
    reconciliation_dir.mkdir()
    result = {
        "schema": "ProviderAvailabilityReconciliationResult/v1",
        "decision": "REQUEUE_TASK",
        "mission_id": mission_id,
        "task_id": task_id,
        "next_wait": {
            "schema": "ProviderAvailabilityWait/v1",
            "mission_id": mission_id,
            "task_id": task_id,
            "agent_instance_id": agent_instance_id,
            "plan_revision": 7,
        },
        "provider_recovery_epoch": {
            "schema": "ProviderRecoveryEpoch/v1",
            "epoch_id": "provider-recovery-epoch-b",
            "epoch": 1,
            "recovered_provider_ids": ["nvidia_nim"],
        },
    }
    (
        reconciliation_dir
        / "provider-availability-reconciliation-result.json"
    ).write_text(json.dumps(result), encoding="utf-8")

    runtime_dir = tmp_path / "runtime"
    evidence = apply_provider_reconciliation_checkpoint(
        plan={"mission_id": mission_id, "plan_revision": 7},
        runtime_dir=runtime_dir,
        provider_reconciliation_dir=reconciliation_dir,
        checkpoint_source_dir=checkpoint_source,
    )

    assert evidence["PROVIDER_REQUEUE_APPLIED"] is True
    assert evidence["PROVIDER_REQUEUE_SESSION_SOURCE"] == "CHECKPOINT_SOURCE"
    assert evidence["PROVIDER_REQUEUE_TOOL_RESULTS_RESTORED"] == 1
    restored_session = json.loads(
        (
            runtime_dir
            / "agent-sessions"
            / f"{task_id}-{agent_instance_id}.json"
        ).read_text(encoding="utf-8")
    )
    assert restored_session["AGENT_INSTANCE_ID"] == agent_instance_id
    assert restored_session["PROVIDER_REQUEUE_READY"] is True
    assert (
        restored_session["PROVIDER_RECOVERY_EPOCH"]["epoch_id"]
        == "provider-recovery-epoch-b"
    )
    assert (runtime_dir / "tool-results" / "provider.json").is_file()


def test_provider_requeue_fails_closed_on_wrong_agent_identity(tmp_path):
    mission_id = "mission-a"
    task_id = "task-02-semantic-diagnosis"
    checkpoint_source = tmp_path / "checkpoint-source"
    session_dir = checkpoint_source / "first-runtime" / "agent-sessions"
    session_dir.mkdir(parents=True)
    (session_dir / "wrong.json").write_text(
        json.dumps({
            "schema": "AgentSession/v1",
            "AGENT_INSTANCE_ID": "agent-other",
            "MISSION_ID": mission_id,
            "TASK_ID": task_id,
        }),
        encoding="utf-8",
    )
    reconciliation_dir = tmp_path / "provider-reconciliation"
    reconciliation_dir.mkdir()
    (
        reconciliation_dir
        / "provider-availability-reconciliation-result.json"
    ).write_text(
        json.dumps({
            "schema": "ProviderAvailabilityReconciliationResult/v1",
            "decision": "REQUEUE_TASK",
            "mission_id": mission_id,
            "task_id": task_id,
            "next_wait": {
                "schema": "ProviderAvailabilityWait/v1",
                "mission_id": mission_id,
                "task_id": task_id,
                "agent_instance_id": "agent-expected",
                "plan_revision": 7,
            },
            "provider_recovery_epoch": {
                "schema": "ProviderRecoveryEpoch/v1",
                "epoch_id": "epoch-b",
            },
        }),
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match="PROVIDER_REQUEUE_AGENT_SESSION_COUNT=0",
    ):
        apply_provider_reconciliation_checkpoint(
            plan={"mission_id": mission_id, "plan_revision": 7},
            runtime_dir=tmp_path / "runtime",
            provider_reconciliation_dir=reconciliation_dir,
            checkpoint_source_dir=checkpoint_source,
        )
