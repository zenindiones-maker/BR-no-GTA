from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "continuous_operation_policy.json"


@dataclass(frozen=True)
class ContinuousOperationPolicy:
    schema: str
    target_ref: str
    cadence: dict[str, int]
    resource_governance: dict[str, int]
    gta6: dict[str, Any]
    system_improvement: dict[str, Any]
    safety: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "target_ref": self.target_ref,
            "cadence": dict(self.cadence),
            "resource_governance": dict(self.resource_governance),
            "gta6": dict(self.gta6),
            "system_improvement": dict(self.system_improvement),
            "safety": dict(self.safety),
        }


def load_continuous_operation_policy(path: str | Path | None = None) -> ContinuousOperationPolicy:
    selected = Path(path) if path is not None else _POLICY_PATH
    data = json.loads(selected.read_text(encoding="utf-8"))
    if data.get("schema") != "br-continuous-operation-policy/v1":
        raise ValueError("continuous operation policy schema mismatch")
    cadence = dict(data.get("cadence") or {})
    resources = dict(data.get("resource_governance") or {})
    required_cadence = {
        "gta6_delta_scan_seconds",
        "daily_consolidation_seconds",
        "system_improvement_seconds",
        "weekly_audit_seconds",
    }
    required_resources = {
        "max_tasks_per_mission",
        "max_retries_per_task",
        "max_reviewer_loops",
        "max_research_sources_no_delta",
        "mission_timeout_seconds",
        "max_parallelism",
        "bounded_memory_bytes",
        "source_freshness_seconds",
    }
    if required_cadence - set(cadence):
        raise ValueError("continuous operation cadence is incomplete")
    if required_resources - set(resources):
        raise ValueError("continuous operation resource governance is incomplete")
    for key in required_cadence:
        if int(cadence[key]) < 3600:
            raise ValueError(f"continuous cadence too aggressive: {key}")
    if int(resources["max_tasks_per_mission"]) > 12:
        raise ValueError("max_tasks_per_mission exceeds bounded governance")
    if int(resources["max_retries_per_task"]) > 3:
        raise ValueError("max_retries_per_task exceeds bounded governance")
    if int(resources["max_reviewer_loops"]) > 3:
        raise ValueError("max_reviewer_loops exceeds bounded governance")
    safety = dict(data.get("safety") or {})
    forbidden_true = {
        "new_voice_synthesis",
        "full_render",
        "youtube_upload",
        "youtube_publication",
        "authority_mutation",
        "memory_gate_bypass",
        "secret_access_expansion",
        "qa_threshold_reduction",
    }
    if any(bool(safety.get(key)) for key in forbidden_true):
        raise PermissionError("continuous policy attempted forbidden side effect")
    return ContinuousOperationPolicy(
        schema=data["schema"],
        target_ref=str(data.get("target_ref") or "").strip(),
        cadence={key: int(value) for key, value in cadence.items()},
        resource_governance={key: int(value) for key, value in resources.items()},
        gta6=dict(data.get("gta6") or {}),
        system_improvement=dict(data.get("system_improvement") or {}),
        safety=safety,
    )
