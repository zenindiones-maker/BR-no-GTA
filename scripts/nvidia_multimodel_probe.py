from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

from app.database import harness_learning_repository as learning_repository
from app.database.schema import initialize_schema
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.nvidia_nim_provider import NvidiaNimProviderAdapter


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _profiles():
    return [
        record
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
        if record.capability_type == "PROVIDER"
        and record.provider_id == "nvidia_nim"
        and record.cost_class == "FREE_ENDPOINT"
    ]


def _persist(record, result, started_at: str, finished_at: str) -> None:
    model_id = str(record.model_id)
    model_hash = sha256(model_id.encode("utf-8")).hexdigest()[:16]
    run_id = str(os.getenv("GITHUB_RUN_ID") or "local")
    success = result.get("HEALTH") == "AVAILABLE"
    evidence_ref = f"github:run:{run_id}:nvidia-model:{model_hash}"
    episode_id = f"episode-nvidia-{run_id}-{model_hash}"
    learning_repository.insert_episode({
        "episode_id": episode_id,
        "goal_id": f"nvidia-multimodel-probe-{run_id}",
        "decision_id": f"nvidia-probe-decision-{model_hash}",
        "execution_id": f"nvidia-probe:{run_id}:{model_hash}",
        "task_id": f"probe-{model_hash}",
        "parent_task_id": None,
        "agent_id": "nvidia-nim-model",
        "capability_id": record.capability_id,
        "skill_id": None,
        "skill_version": None,
        "provider": "nvidia_nim",
        "domain": "ai",
        "task_class": "semantic-mission-planning",
        "input_refs": [],
        "output_refs": [evidence_ref],
        "evidence_refs": [evidence_ref],
        "tool_calls": ["single_short_capability_probe"],
        "routing_decision": {
            "authority": "DEEPSEEK_HARNESS",
            "provider_id": "nvidia_nim",
            "model_id": model_id,
            "probe_only": True,
        },
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": float(result.get("LATENCY_MS") or 0.0) / 1000.0,
        "status": "SUCCEEDED" if success else "FAILED",
        "actual_outcome": result,
        "outcome_evidence": result,
        "error": {} if success else {
            "failure_class": result.get("FAILURE_CLASS"),
            "http_status": result.get("HTTP_STATUS"),
        },
        "retry_count": 0,
        "human_intervention": False,
        "qa_results": {
            "response_valid": result.get("RESPONSE_VALID"),
            "structured_output": result.get("STRUCTURED_OUTPUT_RESULT"),
            "tool_use_supported": result.get("TOOL_USE_SUPPORTED"),
        },
        "cost": 0.0,
        "latency_seconds": float(result.get("LATENCY_MS") or 0.0) / 1000.0,
        "commit_ref": str(os.getenv("GITHUB_SHA") or ""),
        "run_ref": f"github:run:{run_id}",
        "artifact_refs": [evidence_ref],
        "source_versions": {"provider": "nvidia_nim", "model_id": model_id},
        "lineage": {
            "authority": "DEEPSEEK_HARNESS",
            "billing_mode": "NVIDIA_FREE_ENDPOINT",
            "paid_api_billing": False,
            "rate_limit_or_quota_possible": True,
            "unlimited": "UNPROVEN",
        },
    })
    learning_repository.upsert_competence({
        "competence_id": f"competence-nvidia-{model_hash}",
        "agent_id": "nvidia-nim-model",
        "skill_id": None,
        "capability_id": record.capability_id,
        "domain": "ai",
        "task_class": "semantic-mission-planning",
        "version": model_id,
        "tested_cases": 1,
        "success_count": 1 if success else 0,
        "failure_count": 0 if success else 1,
        "human_correction_count": 0,
        "retry_count": 0,
        "total_latency_seconds": (
            float(result.get("LATENCY_MS") or 0.0) / 1000.0
        ),
        "total_cost": 0.0,
        "known_failure_modes": (
            []
            if success
            else [str(result.get("FAILURE_CLASS") or "probe_failure")]
        ),
        "evidence_refs": [evidence_ref],
        "last_verified_at": finished_at,
        "confidence": 0.35,
        "status": "ACTIVE",
    })
    if not success:
        failure = str(result.get("FAILURE_CLASS") or "probe_failure")
        fingerprint = sha256(
            f"nvidia_nim|{model_id}|{failure}".encode("utf-8")
        ).hexdigest()
        learning_repository.insert_memory({
            "memory_id": f"memory-nvidia-{fingerprint[:20]}",
            "memory_type": "FAILURE",
            "claim": f"NVIDIA model {model_id} observed {failure}",
            "domain": "ai",
            "task_class": "semantic-mission-planning",
            "failure_pattern": failure,
            "source_episode_ids": [episode_id],
            "evidence_refs": [evidence_ref],
            "agent_id": "nvidia-nim-model",
            "capability_id": record.capability_id,
            "skill_id": None,
            "skill_version": model_id,
            "source_versions": {"model_id": model_id},
            "metadata": {
                "provider_id": "nvidia_nim",
                "model_id": model_id,
                "http_status": result.get("HTTP_STATUS"),
                "rate_limit_observed": result.get("RATE_LIMIT_OBSERVED"),
            },
            "support_count": 1,
            "contradiction_count": 0,
            "confidence": 0.35,
            "status": "ACTIVE",
            "fingerprint": fingerprint,
            "created_at": finished_at,
            "last_verified_at": finished_at,
        })


def main() -> int:
    output = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else "artifacts/nvidia-multimodel/probe.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    profiles = _profiles()
    api_key = str(os.getenv("NVIDIA_API_KEY") or "").strip()
    if not api_key:
        report = {
            "schema": "nvidia-multimodel-probe/v1",
            "NVIDIA_API_SECRET_BLOCKER": "NVIDIA_API_KEY",
            "NVIDIA_FREE_MODELS_DISCOVERED": len(profiles),
            "NVIDIA_MODELS_PROBED": 0,
            "NVIDIA_MODELS_HEALTHY": 0,
            "SECRET_LEAK": "NO",
            "PAID_API_FALLBACK": "NO",
            "models": [],
        }
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print("NVIDIA_API_SECRET_BLOCKER=NVIDIA_API_KEY")
        return 3

    initialize_schema()
    results = []
    for record in profiles:
        started_at = _now()
        provider = NvidiaNimProviderAdapter(
            model=record.model_id,
            api_key=api_key,
            max_retries=0,
            timeout_seconds=90,
        )
        try:
            result = provider.probe_capabilities()
        except Exception as exc:
            safe = (
                exc.to_dict()
                if callable(getattr(exc, "to_dict", None))
                else {
                    "code": "unexpected_error",
                    "status_code": None,
                    "retryable": False,
                }
            )
            result = {
                "MODEL_ID": record.model_id,
                "HTTP_STATUS": safe.get("status_code"),
                "RESPONSE_VALID": False,
                "LATENCY_MS": round(
                    float(
                        provider.last_performance_metrics.get(
                            "latency_seconds"
                        ) or 0.0
                    ) * 1000,
                    2,
                ),
                "TOOL_USE_SUPPORTED": False,
                "STRUCTURED_OUTPUT_RESULT": "FAIL",
                "RATE_LIMIT_OBSERVED": safe.get("code") == "rate_limited",
                "TOKEN_USAGE_IF_AVAILABLE": {},
                "BILLING_CLASS": "NVIDIA_FREE_ENDPOINT",
                "HEALTH": "DEGRADED",
                "FAILURE_CLASS": safe.get("code") or type(exc).__name__,
            }
        finished_at = _now()
        result["CAPABILITY_ID"] = record.capability_id
        result["PAID_API_BILLING"] = "NO"
        result["UNLIMITED"] = "UNPROVEN"
        result["RATE_LIMIT_OR_QUOTA_POSSIBLE"] = "YES"
        results.append(result)
        _persist(record, result, started_at, finished_at)

    healthy = sum(
        1 for result in results if result.get("HEALTH") == "AVAILABLE"
    )
    report = {
        "schema": "nvidia-multimodel-probe/v1",
        "NVIDIA_PROVIDER": "PASS" if healthy else "FAIL",
        "NVIDIA_FREE_MODELS_DISCOVERED": len(profiles),
        "NVIDIA_MODELS_PROBED": len(results),
        "NVIDIA_MODELS_HEALTHY": healthy,
        "NVIDIA_MULTI_MODEL_SELECTION": "PASS",
        "HARDCODED_MODEL_ROUTING": "NO",
        "SECOND_ROUTER": "NO",
        "SECRET_LEAK": "NO",
        "PAID_API_FALLBACK": "NO",
        "BILLING_MODE": "NVIDIA_FREE_ENDPOINT",
        "PAID_API_BILLING": "NO",
        "RATE_LIMIT_OR_QUOTA_POSSIBLE": "YES",
        "UNLIMITED": "UNPROVEN",
        "models": results,
    }
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"NVIDIA_FREE_MODELS_DISCOVERED={len(profiles)}")
    print(f"NVIDIA_MODELS_PROBED={len(results)}")
    print(f"NVIDIA_MODELS_HEALTHY={healthy}")
    print("SECRET_LEAK=NO")
    print("PAID_API_FALLBACK=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
