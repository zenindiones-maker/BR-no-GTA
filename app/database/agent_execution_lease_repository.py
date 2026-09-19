from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from app.database.connection import get_connection
from app.services.agent_office.delegation import DelegatedTaskLease


def persist_lease(lease: DelegatedTaskLease, *, status: str = "AUTHORIZED") -> None:
    payload = lease.to_dict()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO agent_execution_leases (
                delegation_id, mission_id, task_id, goal_id, harness_decision_id,
                authorization_id, agent_id, capability_ids, base_sha, allowed_paths,
                allowed_tools, allowed_actions, forbidden_actions, input_artifact_refs,
                expected_outputs, acceptance_criteria, evidence_requirements,
                time_budget_seconds, cost_budget, tool_call_budget, retry_budget,
                max_parallelism, expires_at, escalation_conditions, owned_task_class,
                role, read_set, write_set, parent_task_id, authority,
                canonical_push_authority, status, lease_payload
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(delegation_id) DO NOTHING
            """,
            (
                lease.delegation_id, lease.mission_id, lease.task_id, lease.goal_id,
                lease.harness_decision_id, lease.authorization_id, lease.agent_id,
                json.dumps(lease.capability_ids), lease.base_sha,
                json.dumps(lease.allowed_paths), json.dumps(lease.allowed_tools),
                json.dumps(lease.allowed_actions), json.dumps(lease.forbidden_actions),
                json.dumps(lease.input_artifact_refs), json.dumps(lease.expected_outputs),
                json.dumps(lease.acceptance_criteria), json.dumps(lease.evidence_requirements),
                lease.time_budget_seconds, lease.cost_budget, lease.tool_call_budget,
                lease.retry_budget, lease.max_parallelism, lease.expires_at,
                json.dumps(lease.escalation_conditions), lease.owned_task_class, lease.role,
                json.dumps(lease.read_set), json.dumps(lease.write_set), lease.parent_task_id,
                lease.authority, lease.canonical_push_authority, status,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        connection.commit()


def update_lease_status(
    delegation_id: str,
    *,
    status: str,
    result_ref: str | None = None,
    result_hash: str | None = None,
    error: str | None = None,
) -> None:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE agent_execution_leases
            SET status=?, result_ref=?, result_hash=?, error=?,
                completed_at=CASE WHEN ? IN ('COMPLETED','FAILED','ESCALATION_REQUIRED') THEN ? ELSE completed_at END,
                updated_at=CURRENT_TIMESTAMP
            WHERE delegation_id=?
            """,
            (
                status, result_ref, result_hash, error, status,
                datetime.now(timezone.utc).isoformat(), delegation_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"delegation lease not found: {delegation_id}")
        connection.commit()


def get_lease(delegation_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM agent_execution_leases WHERE delegation_id=?",
            (delegation_id,),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    for key in (
        "capability_ids","allowed_paths","allowed_tools","allowed_actions",
        "forbidden_actions","input_artifact_refs","expected_outputs",
        "acceptance_criteria","evidence_requirements","escalation_conditions",
        "read_set","write_set","lease_payload",
    ):
        result[key] = json.loads(result[key])
    return result


def append_task_event(
    *,
    mission_id: str,
    task_id: str,
    delegation_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO agent_execution_events (
                mission_id, task_id, delegation_id, event_type, payload, created_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                mission_id, task_id, delegation_id, event_type,
                json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def list_task_events(*, mission_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id,mission_id,task_id,delegation_id,event_type,payload,created_at
            FROM agent_execution_events
            WHERE mission_id=?
            ORDER BY id
            """,
            (mission_id,),
        ).fetchall()
    return [
        {**dict(row), "payload": json.loads(row["payload"])}
        for row in rows
    ]
