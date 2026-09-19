from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Iterable

from app.database.e2e_stage_checkpoint_repository import (
    insert_checkpoint,
    invalidate_completed_stages,
    latest_completed_checkpoint,
)


PIPELINE_ID = "br-no-gta-system-e2e/v1"
RESEARCH_FRESHNESS_SECONDS = int(os.getenv("BR_E2E_RESEARCH_FRESHNESS_SECONDS", "900"))

STAGE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "research": (),
    "fact-check": ("research",),
    "gta6-brain": ("fact-check",),
    "content-strategy": ("gta6-brain",),
    "editorial-script": ("content-strategy",),
    "script-review": ("editorial-script",),
    "seo": ("editorial-script",),
    "production-management": ("editorial-script",),
    "thumbnail": ("seo",),
    "youtube-package": ("script-review", "production-management", "thumbnail"),
    "production": ("youtube-package",),
    "media-intelligence": ("production",),
    "render": ("media-intelligence",),
    "qa": ("render",),
    "youtube-private-upload": ("qa",),
    "youtube-processing": ("youtube-private-upload",),
    "telegram-human-review": ("youtube-processing",),
    "learning-plane": ("telegram-human-review",),
}

STAGE_CONTRACT_VERSION = {
    "research": "fresh-research/v1",
    "fact-check": "fact-check/v1",
    "gta6-brain": "brain-decision/v1",
    "content-strategy": "youtube-content-strategy/v1",
    "editorial-script": "editorial-script/v2",
    "script-review": "youtube-script-review/v1",
    "seo": "youtube-seo/v1",
    "production-management": "youtube-production-management/v1",
    "thumbnail": "youtube-thumbnail/v1",
    "youtube-package": "youtube-package/v1",
    "production": "production-plan/v1",
    "media-intelligence": "media-intelligence/v1",
    "render": "render-job/v1",
    "qa": "render-qa/v1",
    "youtube-private-upload": "youtube-private-upload/v1",
    "youtube-processing": "youtube-processing/v1",
    "telegram-human-review": "telegram-human-review/v1",
    "learning-plane": "learning-return/v1",
}


@dataclass(frozen=True)
class StageSpec:
    stage_id: str
    input_payload: Any
    code_paths: tuple[str, ...]
    provider_profile_version: str | None = None
    freshness_policy: dict[str, Any] | None = None
    contract_version: str | None = None


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def code_version(paths: Iterable[str], *, root: Path | None = None) -> str:
    root = root or Path(__file__).resolve().parents[2]
    digest = sha256()
    normalized = sorted(dict.fromkeys(str(item) for item in paths if str(item)))
    if not normalized:
        raise ValueError("checkpoint stage requires at least one code path")
    for relative in normalized:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"checkpoint code path missing: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def input_fingerprint(value: Any) -> str:
    return content_hash(value)


def descendants(stage_id: str) -> tuple[str, ...]:
    if stage_id not in STAGE_DEPENDENCIES:
        raise KeyError(stage_id)
    found: set[str] = set()
    pending = [stage_id]
    while pending:
        parent = pending.pop()
        for child, deps in STAGE_DEPENDENCIES.items():
            if parent in deps and child not in found:
                found.add(child)
                pending.append(child)
    return tuple(stage for stage in STAGE_DEPENDENCIES if stage in found)


def invalidate_stage_and_descendants(*, goal_id: str, stage_id: str, reason: str) -> int:
    stages = (stage_id, *descendants(stage_id))
    return invalidate_completed_stages(goal_id=goal_id, stage_ids=stages, reason=reason)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def freshness_is_valid(freshness: dict[str, Any], *, now: datetime | None = None) -> bool:
    if not freshness:
        return True
    now = now or datetime.now(timezone.utc)
    valid_until = _parse_time(str(freshness.get("valid_until") or ""))
    if valid_until is None:
        return bool(freshness.get("reusable", False))
    return now <= valid_until


def evaluate_reuse(
    *,
    goal_id: str,
    spec: StageSpec,
    root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    checkpoint = latest_completed_checkpoint(goal_id=goal_id, stage_id=spec.stage_id)
    expected = {
        "input_fingerprint": input_fingerprint(spec.input_payload),
        "code_version": code_version(spec.code_paths, root=root),
        "contract_version": spec.contract_version or STAGE_CONTRACT_VERSION[spec.stage_id],
        "provider_profile_version": spec.provider_profile_version,
    }
    if checkpoint is None:
        return {"reusable": False, "reason": "MISSING_CHECKPOINT", "expected": expected}
    for field in ("input_fingerprint", "code_version", "contract_version"):
        if str(checkpoint.get(field) or "") != str(expected[field] or ""):
            return {
                "reusable": False,
                "reason": f"{field.upper()}_MISMATCH",
                "checkpoint": checkpoint,
                "expected": expected,
            }
    if (checkpoint.get("provider_profile_version") or None) != (spec.provider_profile_version or None):
        return {
            "reusable": False,
            "reason": "PROVIDER_PROFILE_VERSION_MISMATCH",
            "checkpoint": checkpoint,
            "expected": expected,
        }
    if not freshness_is_valid(dict(checkpoint.get("freshness") or {}), now=now):
        return {
            "reusable": False,
            "reason": "FRESHNESS_EXPIRED",
            "checkpoint": checkpoint,
            "expected": expected,
        }
    if content_hash(checkpoint.get("output_payload") or {}) != str(checkpoint.get("output_hash") or ""):
        return {
            "reusable": False,
            "reason": "OUTPUT_HASH_MISMATCH",
            "checkpoint": checkpoint,
            "expected": expected,
        }
    return {"reusable": True, "reason": "VALID", "checkpoint": checkpoint, "expected": expected}


def record_completed_stage(
    *,
    goal_id: str,
    spec: StageSpec,
    output_payload: dict[str, Any],
    duration_ms: float,
    provenance: dict[str, Any],
    source_run_id: str | None = None,
    source_execution_id: str | None = None,
    freshness: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    return insert_checkpoint(
        pipeline_id=PIPELINE_ID,
        goal_id=goal_id,
        stage_id=spec.stage_id,
        input_fingerprint=input_fingerprint(spec.input_payload),
        output_hash=content_hash(output_payload),
        output_payload=output_payload,
        code_version=code_version(spec.code_paths, root=root),
        contract_version=spec.contract_version or STAGE_CONTRACT_VERSION[spec.stage_id],
        provider_profile_version=spec.provider_profile_version,
        freshness=dict(freshness or spec.freshness_policy or {}),
        provenance={
            "authority": "DEEPSEEK_HARNESS",
            "pipeline_id": PIPELINE_ID,
            **dict(provenance or {}),
        },
        duration_ms=duration_ms,
        source_run_id=source_run_id,
        source_execution_id=source_execution_id,
    )


def build_resume_plan(
    *,
    goal_id: str,
    specs: list[StageSpec],
    root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    decisions: dict[str, dict[str, Any]] = {}
    recomputed: set[str] = set()
    reused: list[str] = []
    saved_ms = 0.0

    for spec in specs:
        deps = STAGE_DEPENDENCIES.get(spec.stage_id)
        if deps is None:
            raise KeyError(spec.stage_id)
        if any(dep in recomputed for dep in deps):
            decision = {"reusable": False, "reason": "DEPENDENCY_INVALIDATED"}
        else:
            decision = evaluate_reuse(goal_id=goal_id, spec=spec, root=root, now=now)
        decisions[spec.stage_id] = decision
        if decision.get("reusable"):
            reused.append(spec.stage_id)
            saved_ms += float((decision.get("checkpoint") or {}).get("duration_ms") or 0.0)
        else:
            recomputed.add(spec.stage_id)
            invalidate_stage_and_descendants(
                goal_id=goal_id,
                stage_id=spec.stage_id,
                reason=str(decision.get("reason") or "INVALIDATED"),
            )

    recomputed_order = [stage for stage in STAGE_DEPENDENCIES if stage in recomputed]
    return {
        "RESUME_FROM_STAGE": recomputed_order[0] if recomputed_order else "COMPLETE",
        "REUSED_STAGE_COUNT": len(reused),
        "RECOMPUTED_STAGE_COUNT": len(recomputed_order),
        "REUSED_TIME_SAVED_MS": round(saved_ms, 3),
        "reused_stages": reused,
        "recomputed_stages": recomputed_order,
        "decisions": decisions,
    }
