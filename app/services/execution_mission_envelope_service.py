from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


EXECUTION_MISSION_ENVELOPE_SCHEMA = "execution-mission-envelope/v1"
EXECUTION_MISSION_ENVELOPE_LIMIT_BYTES = 96 * 1024


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _hashed_ref(
    *,
    value: Any,
    artifact_ref: str,
    evidence_ref: str,
    json_pointer: str | None = None,
) -> dict[str, Any]:
    raw = _canonical_bytes(value)
    result = {
        "artifact_ref": artifact_ref,
        "content_hash": "sha256:" + sha256(raw).hexdigest(),
        "byte_length": len(raw),
        "evidence_ref": evidence_ref,
    }
    if json_pointer:
        result["json_pointer"] = json_pointer
    return result


@dataclass(frozen=True)
class ExecutionMissionEnvelope:
    schema: str
    authority: str
    mission_id: str
    plan_id: str
    goal: dict[str, Any]
    collaboration_plan: dict[str, Any]
    resource_bounds: dict[str, Any]
    human_gates: list[str]
    canonical_mission_plan_ref: dict[str, Any]
    planning_evidence_ref: dict[str, Any]
    payload_profile_ref: dict[str, Any]
    evidence_externalized: bool = True
    evidence_dropped: bool = False
    projection: str = "EXECUTION_CRITICAL_MISSION_ENVELOPE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_execution_mission_envelope(
    mission_plan: dict[str, Any],
    *,
    canonical_artifact_ref: str,
    profile_artifact_ref: str,
    payload_profile: dict[str, Any],
) -> ExecutionMissionEnvelope:
    if not isinstance(mission_plan, dict):
        raise ValueError("canonical MissionPlan must be a dict")
    if mission_plan.get("authority") != "DEEPSEEK_HARNESS":
        raise PermissionError("MissionPlan escaped DeepSeek Harness authority")
    collaboration = deepcopy(mission_plan.get("collaboration_plan") or {})
    tasks = collaboration.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("MissionPlan collaboration DAG is required")

    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("MissionPlan task envelope must be an object")
        # Audit-heavy routing context is persisted in the canonical MissionPlan.
        # Execution keeps all selected identity, scope, budget and authorization
        # fields and revalidates them against the Registry in the child.
        task.pop("selection_evidence", None)

    canonical_ref = _hashed_ref(
        value=mission_plan,
        artifact_ref=canonical_artifact_ref,
        evidence_ref="canonical-mission-plan",
    )
    planning_ref = _hashed_ref(
        value=mission_plan.get("planning_evidence") or {},
        artifact_ref=canonical_artifact_ref,
        evidence_ref="planning-evidence",
        json_pointer="/planning_evidence",
    )
    profile_ref = _hashed_ref(
        value=payload_profile,
        artifact_ref=profile_artifact_ref,
        evidence_ref="mission-plan-payload-profile",
    )
    envelope = ExecutionMissionEnvelope(
        schema=EXECUTION_MISSION_ENVELOPE_SCHEMA,
        authority="DEEPSEEK_HARNESS",
        mission_id=str(mission_plan.get("mission_id") or ""),
        plan_id=str(mission_plan.get("plan_id") or ""),
        goal=deepcopy(mission_plan.get("goal") or {}),
        collaboration_plan=collaboration,
        resource_bounds=deepcopy(mission_plan.get("resource_bounds") or {}),
        human_gates=list(mission_plan.get("human_gates") or ()),
        canonical_mission_plan_ref=canonical_ref,
        planning_evidence_ref=planning_ref,
        payload_profile_ref=profile_ref,
    )
    if not envelope.mission_id or not envelope.plan_id:
        raise ValueError("MissionPlan identity is required")
    if not envelope.goal.get("goal_id"):
        raise ValueError("MissionPlan goal_id is required")
    return envelope


def serialize_execution_mission_envelope(
    envelope: ExecutionMissionEnvelope,
) -> bytes:
    raw = _canonical_bytes(envelope.to_dict())
    if len(raw) > EXECUTION_MISSION_ENVELOPE_LIMIT_BYTES:
        raise ValueError("ExecutionMissionEnvelope exceeds bounded dispatch envelope")
    return raw


def persist_execution_mission_envelope(
    envelope: ExecutionMissionEnvelope,
    *,
    artifact_dir: Path,
) -> dict[str, Any]:
    raw = serialize_execution_mission_envelope(envelope)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / "execution-mission-envelope.json"
    path.write_bytes(raw + b"\n")
    return {
        "EXECUTION_ENVELOPE_TOTAL_BYTES": len(raw),
        "EXECUTION_ENVELOPE_SHA256": sha256(raw).hexdigest(),
        "EXECUTION_ENVELOPE_ARTIFACT": path.name,
        "EXECUTION_ENVELOPE_LT_96_KIB": (
            len(raw) < EXECUTION_MISSION_ENVELOPE_LIMIT_BYTES
        ),
        "EVIDENCE_DROPPED": envelope.evidence_dropped,
        "EVIDENCE_EXTERNALIZED_WITH_HASH": envelope.evidence_externalized,
    }
