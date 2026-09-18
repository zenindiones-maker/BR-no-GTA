from __future__ import annotations

from typing import Any

from app.database import harness_learning_repository as repository
from app.services.operational_efficiency_policy import policy_metadata as operational_efficiency_policy_metadata


MIN_COMPETENCE_CASES = 2


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
    memories = repository.list_memories(
        status="ACTIVE",
        domain=domain,
        task_class=task_class,
        capability_id=capability_id,
        limit=20,
    )
    failures = repository.list_memories(
        status="ACTIVE",
        memory_type="FAILURE",
        domain=domain,
        task_class=task_class,
        capability_id=capability_id,
        limit=20,
    )
    feedback = repository.list_human_corrections(
        affected_capability=capability_id,
        affected_skill=skill_id,
        status="CANDIDATE",
        limit=20,
    )
    skills = repository.list_active_versions(table="harness_skill_versions")
    policies = repository.list_active_versions(table="harness_policy_versions")

    return {
        "domain": domain,
        "task_class": task_class,
        "retrieved_memory_ids": [item["memory_id"] for item in memories],
        "retrieved_failure_memory_ids": [item["memory_id"] for item in failures],
        "retrieved_human_feedback_ids": [item["correction_id"] for item in feedback],
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
        "learning_participated": bool(
            memories or failures or feedback or usable_competence or skills or policies
        ),
    }
