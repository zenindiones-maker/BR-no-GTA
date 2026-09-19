from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from app.database.connection import get_connection


def create_mission(
    *,
    mission_id: str,
    goal_id: str,
    harness_decision_id: str,
    authorization_id: str,
    execution_id: str,
    base_sha: str,
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO agent_office_missions (
                mission_id, goal_id, harness_decision_id, authorization_id,
                execution_id, base_sha, status, request_payload
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                mission_id, goal_id, harness_decision_id, authorization_id,
                execution_id, base_sha, "DELEGATED",
                json.dumps(request_payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        connection.commit()
    mission = get_mission(mission_id)
    assert mission is not None
    return mission


def get_mission(mission_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM agent_office_missions WHERE mission_id=?",
            (mission_id,),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["request_payload"] = json.loads(result["request_payload"])
    result["result_payload"] = (
        None if result["result_payload"] is None else json.loads(result["result_payload"])
    )
    result["reduction_payload"] = (
        None if result["reduction_payload"] is None else json.loads(result["reduction_payload"])
    )
    return result


def claim_mission(mission_id: str, *, worker_id: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE agent_office_missions
            SET status='EXECUTING', claimed_by=?, claimed_at=?, updated_at=CURRENT_TIMESTAMP
            WHERE mission_id=? AND status='DELEGATED'
            """,
            (worker_id, now, mission_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("agent office mission is not claimable")
        connection.commit()
    mission = get_mission(mission_id)
    assert mission is not None
    return mission


def mark_ready_for_reduction(
    mission_id: str,
    *,
    result_payload: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE agent_office_missions
            SET status='READY_FOR_REDUCTION', result_payload=?,
                ready_for_reduction_at=?, updated_at=CURRENT_TIMESTAMP
            WHERE mission_id=? AND status='EXECUTING'
            """,
            (
                json.dumps(result_payload, ensure_ascii=False, sort_keys=True),
                now, mission_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("agent office mission is not executing")
        connection.commit()
    mission = get_mission(mission_id)
    assert mission is not None
    return mission


def mark_mission_failed(mission_id: str, *, error: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE agent_office_missions
            SET status='FAILED', error=?, completed_at=?, updated_at=CURRENT_TIMESTAMP
            WHERE mission_id=? AND status IN ('DELEGATED','EXECUTING')
            """,
            (str(error)[:1200], now, mission_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("agent office mission cannot transition to FAILED")
        connection.commit()
    mission = get_mission(mission_id)
    assert mission is not None
    return mission


def complete_mission(
    mission_id: str,
    *,
    reduction_payload: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE agent_office_missions
            SET status='REDUCED', reduction_payload=?, completed_at=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE mission_id=? AND status='READY_FOR_REDUCTION'
            """,
            (
                json.dumps(reduction_payload, ensure_ascii=False, sort_keys=True),
                now, mission_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("agent office mission is not ready for reduction")
        connection.commit()
    mission = get_mission(mission_id)
    assert mission is not None
    return mission


def mission_status_counts() -> dict[str, int]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT status, COUNT(*) AS count FROM agent_office_missions GROUP BY status"
        ).fetchall()
    return {str(row["status"]): int(row["count"]) for row in rows}
