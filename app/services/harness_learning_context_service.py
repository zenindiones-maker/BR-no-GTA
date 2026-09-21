from __future__ import annotations

from typing import Any
import json
from pathlib import Path

from app.database import harness_learning_repository as repository
from app.services.operational_efficiency_policy import policy_metadata as operational_efficiency_policy_metadata
from app.services.bounded_memory_context_service import build_bounded_memory_context


MIN_COMPETENCE_CASES = 2
_EFFICIENCY_HISTORY_PATH = Path(__file__).resolve().parents[2] / ".run001" / "operational-efficiency-history.json"


def _load_operational_efficiency_history() -> dict[str, Any]:
    if not _EFFICIENCY_HISTORY_PATH.is_file():
        return {"version": "operational-efficiency-history/v1", "observations": [], "baselines": []}
    payload = json.loads(_EFFICIENCY_HISTORY_PATH.read_text(encoding="utf-8"))
    if payload.get("version") != "operational-efficiency-history/v1":
        raise ValueError("operational efficiency history version mismatch")
    if not isinstance(payload.get("observations"), list) or not isinstance(payload.get("baselines"), list):
        raise ValueError("operational efficiency history is malformed")
    return payload



def _competence_metrics(record: dict[str, Any]) -> dict[str, Any]:
    tested = int(record.get("tested_cases") or 0)
    if tested <= 0:
        return {
            **record,
            "success_rate": None,
            "failure_rate": None,
            "human_correction_rate": None,
            "retry_rate": None,
            "mean_latency_seconds": None,
            "mean_cost": None,
            "evidence_sufficient": False,
        }
    return {
        **record,
        "success_rate": float(record.get("success_count") or 0) / tested,
        "failure_rate": float(record.get("failure_count") or 0) / tested,
        "human_correction_rate": float(record.get("human_correction_count") or 0) / tested,
        "retry_rate": float(record.get("retry_count") or 0) / tested,
        "mean_latency_seconds": float(record.get("total_latency_seconds") or 0) / tested,
        "mean_cost": float(record.get("total_cost") or 0) / tested,
        "evidence_sufficient": bool(
            record.get("status") == "ACTIVE" and tested >= MIN_COMPETENCE_CASES
        ),
    }


def load_operational_learning_context(
    *,
    domain: str,
    task_class: str,
    capability_id: str | None = None,
    agent_id: str | None = None,
    skill_id: str | None = None,
    goal_id: str | None = None,
    artifact_ref: str | None = None,
    failure_pattern: str | None = None,
    intent: str | None = None,
) -> dict[str, Any]:
    if not domain or not task_class:
        raise ValueError("domain and task_class are required for operational learning")

    competence = [
        _competence_metrics(item)
        for item in repository.list_competence(
            domain=domain,
            task_class=task_class,
            capability_id=capability_id,
            agent_id=agent_id,
            limit=50,
        )
    ]
    usable_competence = [
        item for item in competence if item.get("evidence_sufficient") is True
    ]
    bounded = build_bounded_memory_context(
        goal_id=goal_id,
        domain=domain,
        task_class=task_class,
        capability_id=capability_id,
        agent_id=agent_id,
        artifact_ref=artifact_ref,
        failure_pattern=failure_pattern,
        intent=intent,
    )
    bounded_dict = bounded.to_dict()
    memories = [
        item
        for item in bounded_dict["operational_memory"]
        if item.get("memory_id")
    ]
    failures = [
        item
        for item in memories
        if item.get("memory_type") == "FAILURE"
    ]
    feedback = repository.list_human_corrections(
        affected_capability=capability_id,
        affected_skill=skill_id,
        status="CANDIDATE",
        limit=20,
    )
    skills = repository.list_active_versions(table="harness_skill_versions")
    policies = repository.list_active_versions(table="harness_policy_versions")
    efficiency_history = _load_operational_efficiency_history()

    return {
        "domain": domain,
        "task_class": task_class,
        "retrieved_memory_ids": [item["memory_id"] for item in memories],
        "retrieved_failure_memory_ids": [item["memory_id"] for item in failures],
        "retrieved_human_feedback_ids": [item["correction_id"] for item in feedback],
        "retrieved_human_decision_ids": [
            item["decision_id"]
            for item in bounded_dict["conversation_memory"]
            if item.get("decision_id")
        ],
        "bounded_memory_context": bounded_dict,
        "MEMORY_RETRIEVE_BEFORE_EXECUTION": "PASS",
        "BOUNDED_MEMORY_CONTEXT": "PASS",
        "competence_records": usable_competence,
        "active_skill_versions": [
            {
                "skill_id": item["skill_id"],
                "version": item["version"],
                "content_ref": item["content_ref"],
                "checksum": item["checksum"],
            }
            for item in skills
        ],
        "active_policy_versions": [
            {
                "policy_id": item["policy_id"],
                "version": item["version"],
                "content_ref": item["content_ref"],
                "checksum": item["checksum"],
            }
            for item in policies
        ],
        "mandatory_operational_policies": [operational_efficiency_policy_metadata()],
        "operational_efficiency_history": efficiency_history,
        "learning_participated": bool(
            memories or failures or feedback
            or bounded_dict["conversation_memory"]
            or bounded_dict["knowledge_memory"]
            or bounded_dict["artifact_lineage_memory"]
            or usable_competence or skills or policies
            or efficiency_history.get("observations")
        ),
    }
