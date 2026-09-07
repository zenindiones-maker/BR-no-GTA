from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection


GTA6_MASTER_AGENT_RUN_STATUSES = {
    "RUNNING",
    "COMPLETED",
    "ERROR",
}


def create_gta6_master_agent_run(
    *,
    execution_id: str,
    cycle_number: int,
    action: str,
    reason: str,
    priority: str,
    confidence: float,
    tool: str | None,
    success: bool,
    started_at: str,
    result: Any = None,
    error_type: str | None = None,
    error: str | None = None,
    status: str = "COMPLETED",
    completed_at: str | None = None,
) -> dict[str, Any]:
    """Persiste um ciclo do GTA6 Master Agent."""

    if not isinstance(execution_id, str) or not execution_id.strip():
        raise ValueError("execution_id must be a non-empty string")

    if not isinstance(cycle_number, int) or isinstance(cycle_number, bool):
        raise ValueError("cycle_number must be an integer")

    if cycle_number <= 0:
        raise ValueError("cycle_number must be greater than zero")

    if not isinstance(action, str) or not action.strip():
        raise ValueError("action must be a non-empty string")

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must be a non-empty string")

    if not isinstance(priority, str) or not priority.strip():
        raise ValueError("priority must be a non-empty string")

    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        raise ValueError("confidence must be between 0 and 1")

    if tool is not None:
        if not isinstance(tool, str) or not tool.strip():
            raise ValueError("tool must be a non-empty string or None")

    if not isinstance(success, bool):
        raise ValueError("success must be a boolean")

    if not isinstance(started_at, str) or not started_at.strip():
        raise ValueError("started_at must be a non-empty string")

    if status not in GTA6_MASTER_AGENT_RUN_STATUSES:
        raise ValueError(
            "status must be one of RUNNING, COMPLETED, ERROR"
        )

    if completed_at is not None:
        if not isinstance(completed_at, str) or not completed_at.strip():
            raise ValueError(
                "completed_at must be a non-empty string or None"
            )

    if error_type is not None:
        if not isinstance(error_type, str) or not error_type.strip():
            raise ValueError(
                "error_type must be a non-empty string or None"
            )

    if error is not None:
        if not isinstance(error, str) or not error.strip():
            raise ValueError(
                "error must be a non-empty string or None"
            )

    try:
        result_json = json.dumps(
            result,
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "result must be JSON serializable"
        ) from exc

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO gta6_master_agent_runs (
                execution_id,
                cycle_number,
                status,
                action,
                reason,
                priority,
                confidence,
                tool,
                success,
                result_json,
                error_type,
                error,
                started_at,
                completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                execution_id.strip(),
                cycle_number,
                status,
                action.strip(),
                reason.strip(),
                priority.strip(),
                float(confidence),
                tool.strip() if tool is not None else None,
                int(success),
                result_json,
                (
                    error_type.strip()
                    if error_type is not None
                    else None
                ),
                error.strip() if error is not None else None,
                started_at.strip(),
                (
                    completed_at.strip()
                    if completed_at is not None
                    else None
                ),
            ),
        )

        connection.commit()

        row = connection.execute(
            """
            SELECT
                id,
                execution_id,
                cycle_number,
                status,
                action,
                reason,
                priority,
                confidence,
                tool,
                success,
                result_json,
                error_type,
                error,
                started_at,
                completed_at,
                created_at
            FROM gta6_master_agent_runs
            WHERE id = ?
            LIMIT 1
            """,
            (cursor.lastrowid,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                "GTA6 Master Agent run was not persisted"
            )

        record = dict(row)
        record["success"] = bool(record["success"])
        record["result"] = json.loads(record.pop("result_json"))

        return record

    finally:
        connection.close()


def get_gta6_master_agent_run(
    run_id: int,
) -> dict[str, Any] | None:
    """Retorna um ciclo persistido do GTA6 Master Agent."""

    if not isinstance(run_id, int) or isinstance(run_id, bool):
        raise ValueError("run_id must be an integer")

    if run_id <= 0:
        raise ValueError("run_id must be greater than zero")

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                execution_id,
                cycle_number,
                status,
                action,
                reason,
                priority,
                confidence,
                tool,
                success,
                result_json,
                error_type,
                error,
                started_at,
                completed_at,
                created_at
            FROM gta6_master_agent_runs
            WHERE id = ?
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()

        if row is None:
            return None

        record = dict(row)
        record["success"] = bool(record["success"])
        record["result"] = json.loads(record.pop("result_json"))

        return record

    finally:
        connection.close()


def list_gta6_master_agent_runs(
    *,
    execution_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Lista ciclos persistidos do GTA6 Master Agent."""

    if execution_id is not None:
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise ValueError(
                "execution_id must be a non-empty string or None"
            )

    if status is not None and status not in GTA6_MASTER_AGENT_RUN_STATUSES:
        raise ValueError(
            "status must be one of RUNNING, COMPLETED, ERROR or None"
        )

    connection = get_connection()

    try:
        query = """
            SELECT
                id,
                execution_id,
                cycle_number,
                status,
                action,
                reason,
                priority,
                confidence,
                tool,
                success,
                result_json,
                error_type,
                error,
                started_at,
                completed_at,
                created_at
            FROM gta6_master_agent_runs
        """

        conditions: list[str] = []
        parameters: list[Any] = []

        if execution_id is not None:
            conditions.append("execution_id = ?")
            parameters.append(execution_id.strip())

        if status is not None:
            conditions.append("status = ?")
            parameters.append(status)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY cycle_number ASC, id ASC"

        rows = connection.execute(
            query,
            parameters,
        ).fetchall()

        results = []

        for row in rows:
            record = dict(row)
            record["success"] = bool(record["success"])
            record["result"] = json.loads(record.pop("result_json"))
            results.append(record)

        return results

    finally:
        connection.close()
