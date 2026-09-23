import json
from pathlib import Path

from app.services.execution_mission_envelope_service import (
    EXECUTION_MISSION_ENVELOPE_LIMIT_BYTES,
    build_execution_mission_envelope,
    persist_execution_mission_envelope,
    serialize_execution_mission_envelope,
)


def _large_plan():
    learning = {
        "operational_memory": [{"claim": "x" * 9000}],
        "failure_memory": [{"claim": "y" * 5000}],
    }
    tasks = []
    for index in range(4):
        tasks.append({
            "task_id": f"task-{index}",
            "capability_id": f"capability-{index}",
            "action": "DEVELOPMENT",
            "objective": "bounded objective",
            "dependencies": [] if index == 0 else [f"task-{index-1}"],
            "input_refs": [],
            "expected_output": "evidence",
            "routing_id": f"route-{index}",
            "candidate_capability_ids": [f"capability-{index}"],
            "selected_executor_binding": "app.exec.binding",
            "selected_agent_id": f"agent-{index}",
            "selected_skill_id": None,
            "evidence_expectations": ["typed evidence"],
            "read_scope": ["app/**"],
            "write_scope": [] if index < 2 else ["app/**"],
            "allowed_tools": ["git", "python"],
            "allowed_side_effects": [],
            "forbidden_side_effects": ["publication"],
            "time_budget_seconds": 300,
            "context_budget_bytes": 32768,
            "tool_budget": 16,
            "retry_budget": 1,
            "idempotency_key": f"idem-{index}",
            "mission_id": "mission-big",
            "goal_id": "goal-big",
            "capability_version": "1",
            "selection_evidence": {
                "routing_id": f"route-{index}",
                "policy_metadata": {
                    "learning_context": learning,
                    "bounded_memory_context": learning,
                },
            },
        })
    return {
        "authority": "DEEPSEEK_HARNESS",
        "mission_id": "mission-big",
        "plan_id": "plan-big",
        "goal": {
            "goal_id": "goal-big",
            "human_goal": "profile the planner",
            "mission_class": "SYSTEM_IMPROVEMENT",
        },
        "collaboration_plan": {
            "mission_id": "mission-big",
            "goal_id": "goal-big",
            "authority": "DEEPSEEK_HARNESS",
            "tasks": tasks,
            "execution_levels": [[f"task-{i}"] for i in range(4)],
        },
        "bounded_memory_context": learning,
        "resource_bounds": {
            "max_parallelism": 2,
            "max_retries_per_task": 1,
            "mission_timeout_seconds": 1200,
            "bounded_memory_bytes": 65536,
        },
        "provider_health": {"nvidia_nim": learning},
        "known_bad_paths_avoided": ["blocked-" + "z" * 3000],
        "human_gates": ["promotion"],
        "semantic_plan_proposal": {"raw": "p" * 30000},
        "planning_evidence": {
            "provider_evidence": {"routing": {"policy_metadata": learning}},
            "selection": [learning, learning],
        },
    }


def test_execution_envelope_externalizes_audit_evidence_without_semantic_loss(tmp_path: Path):
    plan = _large_plan()
    full_raw = json.dumps(
        plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    assert len(full_raw) > EXECUTION_MISSION_ENVELOPE_LIMIT_BYTES
    profile = {
        "MISSION_PLAN_TOTAL_BYTES": len(full_raw),
        "MISSION_PLAN_SHA256": "placeholder",
    }
    envelope = build_execution_mission_envelope(
        plan,
        canonical_artifact_ref=(
            "github:run:1:artifact-file:canonical-mission-plan.json"
        ),
        profile_artifact_ref=(
            "github:run:1:artifact-file:mission-plan-payload-profile.json"
        ),
        payload_profile=profile,
    )
    data = envelope.to_dict()
    raw = serialize_execution_mission_envelope(envelope)
    assert len(raw) < EXECUTION_MISSION_ENVELOPE_LIMIT_BYTES
    assert data["authority"] == "DEEPSEEK_HARNESS"
    assert data["mission_id"] == plan["mission_id"]
    assert data["plan_id"] == plan["plan_id"]
    assert data["goal"] == plan["goal"]
    assert data["resource_bounds"] == plan["resource_bounds"]
    assert data["human_gates"] == plan["human_gates"]
    assert data["evidence_dropped"] is False
    assert data["evidence_externalized"] is True
    for before, after in zip(
        plan["collaboration_plan"]["tasks"],
        data["collaboration_plan"]["tasks"],
    ):
        assert "selection_evidence" in before
        assert "selection_evidence" not in after
        for key in (
            "task_id", "capability_id", "selected_executor_binding",
            "selected_agent_id", "selected_skill_id", "capability_version",
            "read_scope", "write_scope", "allowed_tools", "idempotency_key",
        ):
            assert after[key] == before[key]
    assert data["canonical_mission_plan_ref"]["content_hash"].startswith(
        "sha256:"
    )
    assert data["planning_evidence_ref"]["content_hash"].startswith("sha256:")
    result = persist_execution_mission_envelope(
        envelope,
        artifact_dir=tmp_path,
    )
    assert result["EXECUTION_ENVELOPE_LT_96_KIB"] is True
    assert result["EVIDENCE_DROPPED"] is False
    assert result["EVIDENCE_EXTERNALIZED_WITH_HASH"] is True
    assert (tmp_path / "execution-mission-envelope.json").is_file()
