from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
from uuid import uuid4

from app.database.connection import get_connection


STATUS_COMPLETED = "COMPLETED"
STATUS_INVALIDATED = "INVALIDATED"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _row(row) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["output_payload"] = _loads(item.get("output_payload"), {})
    item["freshness"] = _loads(item.get("freshness"), {})
    item["provenance"] = _loads(item.get("provenance"), {})
    return item


def insert_checkpoint(
    *,
    pipeline_id: str,
    goal_id: str,
    stage_id: str,
    input_fingerprint: str,
    output_hash: str,
    output_payload: dict[str, Any],
    code_version: str,
    contract_version: str,
    provider_profile_version: str | None,
    freshness: dict[str, Any],
    provenance: dict[str, Any],
    duration_ms: float,
    source_run_id: str | None,
    source_execution_id: str | None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    checkpoint_id = f"checkpoint-{uuid4()}"
    completed_at = completed_at or _utcnow()
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO e2e_stage_checkpoints (
                checkpoint_id, pipeline_id, goal_id, stage_id,
                input_fingerprint, output_hash, output_payload,
                code_version, contract_version, provider_profile_version,
                freshness, provenance, status, duration_ms,
                source_run_id, source_execution_id, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checkpoint_id,
                pipeline_id,
                goal_id,
                stage_id,
                input_fingerprint,
                output_hash,
                json.dumps(output_payload, ensure_ascii=False, sort_keys=True, default=str),
                code_version,
                contract_version,
                provider_profile_version,
                json.dumps(freshness, ensure_ascii=False, sort_keys=True, default=str),
                json.dumps(provenance, ensure_ascii=False, sort_keys=True, default=str),
                STATUS_COMPLETED,
                max(0.0, float(duration_ms)),
                source_run_id,
                source_execution_id,
                completed_at,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM e2e_stage_checkpoints WHERE checkpoint_id = ?",
            (checkpoint_id,),
        ).fetchone()
        return _row(row) or {}
    finally:
        connection.close()


def latest_completed_checkpoint(*, goal_id: str, stage_id: str) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT * FROM e2e_stage_checkpoints
            WHERE goal_id = ? AND stage_id = ? AND status = ?
            ORDER BY completed_at DESC, created_at DESC
            LIMIT 1
            """,
            (goal_id, stage_id, STATUS_COMPLETED),
        ).fetchone()
        return _row(row)
    finally:
        connection.close()


def list_goal_checkpoints(goal_id: str) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT * FROM e2e_stage_checkpoints
            WHERE goal_id = ?
            ORDER BY completed_at ASC, stage_id ASC
            """,
            (goal_id,),
        ).fetchall()
        return [_row(row) or {} for row in rows]
    finally:
        connection.close()


def invalidate_completed_stages(
    *,
    goal_id: str,
    stage_ids: list[str] | tuple[str, ...],
    reason: str,
) -> int:
    stage_ids = tuple(dict.fromkeys(str(item) for item in stage_ids if str(item)))
    if not stage_ids:
        return 0
    placeholders = ",".join("?" for _ in stage_ids)
    now = _utcnow()
    connection = get_connection()
    try:
        cursor = connection.execute(
            f"""
            UPDATE e2e_stage_checkpoints
            SET status = ?, invalidated_at = ?, invalidation_reason = ?
            WHERE goal_id = ?
              AND status = ?
              AND stage_id IN ({placeholders})
            """,
            (
                STATUS_INVALIDATED,
                now,
                reason[:500],
                goal_id,
                STATUS_COMPLETED,
                *stage_ids,
            ),
        )
        connection.commit()
        return int(cursor.rowcount or 0)
    finally:
        connection.close()
