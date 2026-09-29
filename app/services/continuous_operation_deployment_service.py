from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping


DEPLOYMENT_SCHEMA = "ContinuousOperationDeployment/v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9._/-]+$")


def _parse_time(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("promoted_at is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("promoted_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("promoted_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def validate_continuous_operation_deployment(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    data = dict(payload)
    if data.get("schema") != DEPLOYMENT_SCHEMA:
        raise ValueError("deployment schema mismatch")

    execution_ref = str(data.get("execution_ref") or "").strip()
    if (
        not execution_ref
        or len(execution_ref) > 180
        or execution_ref.startswith("-")
        or ".." in execution_ref
        or "@{" in execution_ref
        or not _SAFE_REF.fullmatch(execution_ref)
    ):
        raise ValueError("unsafe execution_ref")

    expected_sha = str(data.get("expected_sha") or "").strip().lower()
    if not _SHA40.fullmatch(expected_sha):
        raise ValueError("expected_sha must be an exact 40-character git sha")

    workflow_contract_version = str(
        data.get("workflow_contract_version") or ""
    ).strip()
    if not workflow_contract_version.startswith("continuous-executor/"):
        raise ValueError("workflow_contract_version is required")

    policy_sha256 = str(data.get("policy_sha256") or "").strip().lower()
    if not _SHA256.fullmatch(policy_sha256):
        raise ValueError("policy_sha256 must be sha256")

    if data.get("enabled") is not True:
        raise PermissionError("continuous deployment is not enabled")

    promoted_at = _parse_time(str(data.get("promoted_at") or ""))
    promotion_evidence_refs = tuple(
        dict.fromkeys(
            str(item).strip()
            for item in (data.get("promotion_evidence_refs") or ())
            if str(item).strip()
        )
    )
    if not promotion_evidence_refs:
        raise PermissionError("promotion evidence is required")

    cadence_seconds = int(data.get("cadence_seconds") or 0)
    if cadence_seconds < 300:
        raise ValueError("cadence_seconds must be at least 300")

    cycle_kind = str(data.get("cycle_kind") or "").strip()
    if not cycle_kind:
        raise ValueError("cycle_kind is required")

    return {
        **data,
        "execution_ref": execution_ref,
        "expected_sha": expected_sha,
        "workflow_contract_version": workflow_contract_version,
        "policy_sha256": policy_sha256,
        "promoted_at": promoted_at.isoformat(),
        "promotion_evidence_refs": list(promotion_evidence_refs),
        "cadence_seconds": cadence_seconds,
        "cycle_kind": cycle_kind,
    }


def load_continuous_operation_deployment(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("continuous deployment descriptor is unreadable") from exc
    if not isinstance(payload, dict):
        raise ValueError("continuous deployment descriptor must be an object")
    return validate_continuous_operation_deployment(payload)


def build_logical_cycle_id(
    deployment: Mapping[str, Any],
    *,
    trigger_kind: str,
    now: str | datetime,
    mode: str = "scheduled",
    request_id: str | None = None,
) -> str:
    data = validate_continuous_operation_deployment(deployment)
    trigger = str(trigger_kind or "").strip()
    normalized_mode = str(mode or "scheduled").strip().lower()
    if normalized_mode not in {"scheduled", "proof"}:
        raise ValueError("unsupported continuous mode")

    if isinstance(now, datetime):
        current = now
    else:
        current = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)

    cadence = int(data["cadence_seconds"])
    epoch_seconds = int(current.timestamp())
    window_start = epoch_seconds - (epoch_seconds % cadence)

    if normalized_mode == "proof":
        normalized_request = str(request_id or "").strip()
        if not normalized_request:
            raise ValueError("request_id is required for proof mode")
        logical_event = {
            "semantics": "NON_COALESCIBLE_EXPLICIT_PROOF",
            "request_id": normalized_request,
        }
    else:
        logical_event = {
            "semantics": "COALESCIBLE_LATEST_STATE_RECONCILIATION",
            "window_start_epoch": window_start,
        }

    identity = {
        "schema": "ContinuousOperationLogicalCycleIdentity/v1",
        "expected_sha": data["expected_sha"],
        "policy_sha256": data["policy_sha256"],
        "cycle_kind": data["cycle_kind"],
        "mode": normalized_mode,
        "logical_event": logical_event,
    }
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "continuous-cycle-" + sha256(raw).hexdigest()[:24]
