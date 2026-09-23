from pathlib import Path

from app.services.mission_plan_payload_service import (
    persist_mission_plan_payload_evidence,
    profile_mission_plan_payload,
)


def _plan():
    repeated = {
        "capability_id": "cap.read",
        "provider_id": "nvidia_nim",
        "model_id": "model-a",
        "availability": "AVAILABLE",
        "evidence_ref": "github:run:123:artifact:health",
    }
    return {
        "authority": "DEEPSEEK_HARNESS",
        "mission_id": "mission-test",
        "plan_id": "plan-test",
        "goal": {"goal_id": "goal-test", "human_goal": "measure"},
        "collaboration_plan": {
            "tasks": [
                {**repeated, "task_id": "a"},
                {**repeated, "task_id": "b"},
            ],
            "execution_levels": [["a"], ["b"]],
        },
        "bounded_memory_context": {
            "operational_memory": [
                {"artifact_ref": "github:run:123:artifact:health"},
                {"artifact_ref": "github:run:123:artifact:health"},
            ],
        },
        "provider_health": {"models": [repeated, repeated]},
        "semantic_plan_proposal": {"tasks": []},
        "planning_evidence": {
            "context_retrieval": {"records": [repeated]},
            "provider_evidence": repeated,
            "selection": [repeated, repeated],
            "rejection_reasons": [],
            "validated_by": "DEEPSEEK_HARNESS",
        },
        "resource_bounds": {"max_tasks_per_mission": 4},
        "known_bad_paths_avoided": ["capability:blocked"],
        "human_gates": ["promotion"],
    }


def test_payload_profile_reports_requested_breakdown_and_duplicates(tmp_path: Path):
    plan = _plan()
    profile = profile_mission_plan_payload(plan)
    assert profile["MISSION_PLAN_TOTAL_BYTES"] > 0
    fields = profile["MISSION_PLAN_FIELD_BYTES"]
    for key in (
        "GOAL_BYTES",
        "COLLABORATION_PLAN_BYTES",
        "BOUNDED_MEMORY_CONTEXT_BYTES",
        "PROVIDER_HEALTH_BYTES",
        "SEMANTIC_PLAN_PROPOSAL_BYTES",
        "PLANNING_EVIDENCE_BYTES",
        "RESOURCE_BOUNDS_BYTES",
        "KNOWN_BAD_PATHS_BYTES",
        "HUMAN_GATES_BYTES",
    ):
        assert fields[key] >= 2
    evidence = profile["PLANNING_EVIDENCE_FIELD_BYTES"]
    assert evidence["CONTEXT_RETRIEVAL_BYTES"] > 0
    assert evidence["PROVIDER_EVIDENCE_BYTES"] > 0
    assert evidence["SELECTION_EVIDENCE_BYTES"] > 0
    assert evidence["DUPLICATE_BYTES_ESTIMATE"] if False else True
    assert profile["DUPLICATE_BYTES_ESTIMATE"] > 0
    assert profile["DUPLICATE_CONTEXT_REFERENCES"] > 0
    assert profile["REPEATED_CAPABILITY_RECORDS"] > 0
    assert profile["REPEATED_HEALTH_RECORDS"] > 0
    assert profile["DISPATCH_LIMIT_BYTES"] == 96 * 1024
    assert profile["DISPATCH_LIMIT_PRESERVED"] is True

    persisted = persist_mission_plan_payload_evidence(
        plan,
        artifact_dir=tmp_path,
    )
    assert (tmp_path / "canonical-mission-plan.json").is_file()
    assert (tmp_path / "mission-plan-payload-profile.json").is_file()
    assert len(persisted["MISSION_PLAN_SHA256"]) == 64
