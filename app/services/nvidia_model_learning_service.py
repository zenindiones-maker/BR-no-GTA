from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from app.database import harness_learning_repository as learning_repository
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nvidia_record(model_id: str):
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if (
            record.capability_type == "PROVIDER"
            and str(record.provider_id or "").lower().replace("-", "_")
            == "nvidia_nim"
            and str(record.model_id or "") == model_id
        ):
            return record
    raise ValueError(f"unregistered NVIDIA model: {model_id}")


def record_nvidia_semantic_model_observation(
    *,
    model_id: str,
    goal_id: str,
    routing_id: str,
    success: bool,
    latency_ms: float,
    failure_class: str | None = None,
    http_status: int | None = None,
    retry_count: int = 0,
    structured_output_valid: bool | None = None,
    mission_proposal_schema_valid: bool | None = None,
    run_id: str | None = None,
    evidence_ref: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    record = _nvidia_record(str(model_id))
    normalized_run_id = str(run_id or "").strip() or "local"
    model_hash = sha256(str(model_id).encode("utf-8")).hexdigest()[:16]
    ref = (
        str(evidence_ref or "").strip()
        or f"github:run:{normalized_run_id}:nvidia-model:{model_hash}:semantic"
    )
    finished = str(finished_at or "").strip() or _utcnow()
    started = str(started_at or "").strip() or finished
    latency = max(0.0, float(latency_ms or 0.0))
    failure = str(failure_class or "").strip() or (
        None if success else "semantic_provider_failure"
    )
    observation_fingerprint = sha256(
        (
            f"{normalized_run_id}|{routing_id}|{model_id}|"
            f"{'PASS' if success else failure}|{latency:.3f}"
        ).encode("utf-8")
    ).hexdigest()
    episode_id = f"episode-nvidia-semantic-{observation_fingerprint[:24]}"
    outcome = {
        "MODEL_ID": str(model_id),
        "PROVIDER": "nvidia_nim",
        "BILLING_CLASS": "NVIDIA_FREE_ENDPOINT",
        "PAID_API_BILLING": "NO",
        "HEALTH": "AVAILABLE" if success else "DEGRADED",
        "FAILURE_CLASS": failure,
        "LATENCY_MS": latency,
        "HTTP_STATUS": http_status,
        "RESPONSE_VALID": bool(success),
        "STRUCTURED_OUTPUT_VALID": structured_output_valid,
        "MISSION_PROPOSAL_SCHEMA_VALID": mission_proposal_schema_valid,
        "EVIDENCE_REF": ref,
        "observed": True,
    }
    persisted, inserted = learning_repository.insert_episode({
        "episode_id": episode_id,
        "goal_id": str(goal_id or "semantic-planning"),
        "decision_id": str(routing_id or "semantic-routing"),
        "execution_id": f"nvidia-semantic:{normalized_run_id}:{observation_fingerprint[:16]}",
        "task_id": f"semantic-model-{model_hash}",
        "parent_task_id": None,
        "agent_id": "nvidia-nim-model",
        "capability_id": record.capability_id,
        "skill_id": None,
        "skill_version": str(model_id),
        "provider": "nvidia_nim",
        "domain": "ai",
        "task_class": "semantic-mission-planning",
        "input_refs": [],
        "output_refs": [ref] if success else [],
        "evidence_refs": [ref],
        "tool_calls": ["harness_ai_provider_service.execute_harness_ai_generation"],
        "routing_decision": {
            "authority": "DEEPSEEK_HARNESS",
            "routing_id": str(routing_id or ""),
            "provider_id": "nvidia_nim",
            "model_id": str(model_id),
        },
        "started_at": started,
        "finished_at": finished,
        "duration_seconds": latency / 1000.0,
        "status": "COMPLETED" if success else "FAILED",
        "actual_outcome": outcome,
        "outcome_evidence": outcome,
        "error": None if success else {
            "failure_class": failure,
            "http_status": http_status,
        },
        "retry_count": int(retry_count or 0),
        "human_intervention": False,
        "qa_results": {
            "structured_output_valid": structured_output_valid,
            "mission_proposal_schema_valid": mission_proposal_schema_valid,
        },
        "cost": 0.0,
        "latency_seconds": latency / 1000.0,
        "commit_ref": "",
        "run_ref": (
            f"github:run:{normalized_run_id}"
            if normalized_run_id.isdigit()
            else f"local:{normalized_run_id}"
        ),
        "artifact_refs": [ref],
        "source_versions": {
            "provider": "nvidia_nim",
            "model_id": str(model_id),
        },
        "lineage": {
            "authority": "DEEPSEEK_HARNESS",
            "billing_mode": "NVIDIA_FREE_ENDPOINT",
            "paid_api_billing": False,
            "routing_id": str(routing_id or ""),
        },
    })
    learning_repository.upsert_competence({
        "competence_id": f"competence-nvidia-{model_hash}",
        "agent_id": "nvidia-nim-model",
        "skill_id": None,
        "capability_id": record.capability_id,
        "domain": "ai",
        "task_class": "semantic-mission-planning",
        "version": str(model_id),
        "tested_cases": 1,
        "success_count": 1 if success else 0,
        "failure_count": 0 if success else 1,
        "human_correction_count": 0,
        "retry_count": int(retry_count or 0),
        "total_latency_seconds": latency / 1000.0,
        "total_cost": 0.0,
        "known_failure_modes": [] if success else [str(failure)],
        "evidence_refs": [ref],
        "last_verified_at": finished,
        "confidence": 0.5,
        "status": "ACTIVE",
    })
    memory_id = None
    if not success:
        memory_fingerprint = sha256(
            f"nvidia_nim|{model_id}|{failure}".encode("utf-8")
        ).hexdigest()
        existing = learning_repository.find_failure_memory(
            domain="ai",
            task_class="semantic-mission-planning",
            capability_id=record.capability_id,
            failure_pattern=str(failure),
            skill_version=str(model_id),
        )
        if existing is None:
            memory, _ = learning_repository.insert_memory({
                "memory_id": f"memory-nvidia-{memory_fingerprint[:20]}",
                "memory_type": "FAILURE",
                "claim": f"NVIDIA model {model_id} observed {failure}",
                "domain": "ai",
                "task_class": "semantic-mission-planning",
                "failure_pattern": str(failure),
                "source_episode_ids": [episode_id],
                "evidence_refs": [ref],
                "agent_id": "nvidia-nim-model",
                "capability_id": record.capability_id,
                "skill_id": None,
                "skill_version": str(model_id),
                "source_versions": {"model_id": str(model_id)},
                "metadata": {
                    "provider_id": "nvidia_nim",
                    "model_id": str(model_id),
                    "http_status": http_status,
                    "latency_ms": latency,
                },
                "support_count": 1,
                "contradiction_count": 0,
                "confidence": 0.7,
                "status": "ACTIVE",
                "fingerprint": memory_fingerprint,
                "created_at": finished,
                "last_verified_at": finished,
            })
            memory_id = memory["memory_id"]
        else:
            learning_repository.add_failure_memory_observation(
                existing["memory_id"],
                episode_id=episode_id,
                evidence_refs=[ref],
                metadata={
                    "run_id": normalized_run_id,
                    "model_id": str(model_id),
                    "latency_ms": latency,
                    "failure_class": str(failure),
                },
                last_verified_at=finished,
            )
            memory_id = existing["memory_id"]
    return {
        "episode_id": persisted["episode_id"],
        "inserted": bool(inserted),
        "memory_id": memory_id,
        "evidence_ref": ref,
        "capability_id": record.capability_id,
    }
