from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any

SCHEMA_VERSION = "DevelopmentProgressLedger/v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def ledger_digest(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    return sha256(canonical_json(clean)).hexdigest()


@dataclass
class DevelopmentProgressLedger:
    mission_id: str
    goal_digest: str
    canonical_branch: str
    canonical_base_sha: str
    recovery_ref: str
    checkpoint_sequence: int
    plan_steps: list[str]
    completed_steps: list[str]
    current_step: str | None
    next_step: str | None
    open_blockers: list[Any]
    decisions: list[Any]
    rejected_directions: list[Any]
    known_failures: list[Any]
    validation_state: str
    tests: dict[str, Any]
    evidence_refs: list[Any]
    artifact_refs: list[Any]
    do_not_repeat: list[Any]
    side_effects: dict[str, Any]
    latest_verified_checkpoint_id: str | None = None
    latest_verified_checkpoint_sha: str | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        validate_ledger(payload)
        return payload


_REQUIRED = {
    "schema_version","mission_id","goal_digest","canonical_branch","canonical_base_sha",
    "recovery_ref","latest_verified_checkpoint_id","latest_verified_checkpoint_sha",
    "checkpoint_sequence","plan_steps","completed_steps","current_step","next_step",
    "open_blockers","decisions","rejected_directions","known_failures","validation_state",
    "tests","evidence_refs","artifact_refs","do_not_repeat","side_effects","updated_at",
}


def validate_ledger(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("DevelopmentProgressLedger must be an object")
    missing = sorted(_REQUIRED - set(payload))
    if missing:
        raise ValueError(f"DevelopmentProgressLedger missing fields: {missing}")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported DevelopmentProgressLedger schema")
    if _SHA256.fullmatch(str(payload["goal_digest"])) is None:
        raise ValueError("goal_digest must be sha256")
    if _SHA40.fullmatch(str(payload["canonical_base_sha"])) is None:
        raise ValueError("canonical_base_sha must be exact git sha")
    if not isinstance(payload["checkpoint_sequence"], int) or payload["checkpoint_sequence"] < 0:
        raise ValueError("checkpoint_sequence must be monotonic non-negative integer")
    if not isinstance(payload["tests"], dict):
        raise ValueError("tests must be structured")
    side = payload["side_effects"]
    if not isinstance(side, dict):
        raise ValueError("side_effects must be structured")
    for key in ("known_completed","unknown_requires_reconciliation"):
        if key not in side or not isinstance(side[key], list):
            raise ValueError(f"side_effects.{key} must be a list")
