from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.database.connection import get_connection


GTA6_SCHEDULER_EVENT_TYPES = {
    "EXECUTED",
    "ERROR",
    "MISSED",
    "MAX_INSTANCES",
}


def create_gta6_scheduler_event(
    *,
    job_id: str,
    event_type: str,
    scheduled_run_time: datetime | None = None,
    scheduled_run_times: tuple[datetime, ...] = (),
    observed_at: datetime,
    exception: str | None = None,
    traceback_text: str | None = None,
    run_id: int | None = None,
    execution_id: str | None = None,
) -> dict[str, Any]:
    """Persiste um evento operacional do scheduler GTA 6."""

    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("job_id must be a non-empty string")

    if event_type not in GTA6_SCHEDULER_EVENT_TYPES:
        raise ValueError(
            "event_type must be one of "
            "EXECUTED, ERROR, MISSED, MAX_INSTANCES"
        )

    if scheduled_run_time is not None and not isinstance(
        scheduled_run_time,
        datetime,
    ):
        raise ValueError(
            "scheduled_run_time must be a datetime or None"
        )

    if not isinstance(scheduled_run_times, tuple):
        raise ValueError(
            "scheduled_run_times must be a tuple"
        )

    for value in scheduled_run_times:
        if not isinstance(value, datetime):
            raise ValueError(
                "scheduled_run_times must contain only datetime values"
            )

    if not isinstance(observed_at, datetime):
        raise ValueError("observed_at must be a datetime")

    if exception is not None:
        if not isinstance(exception, str) or not exception.strip():
            raise ValueError(
                "exception must be a non-empty string or None"
            )

    if traceback_text is not None:
        if not isinstance(traceback_text, str):
            raise ValueError(
                "traceback_text must be a string or None"
            )

    if run_id is not None:
        if not isinstance(run_id, int) or isinstance(run_id, bool):
            raise ValueError("run_id must be an integer or None")
        if run_id <= 0:
            raise ValueError("run_id must be greater than zero")

    if execution_id is not None:
        if (
            not isinstance(execution_id, str)
            or not execution_id.strip()
        ):
            raise ValueError(
                "execution_id must be a non-empty string or None"
            )

    scheduled_run_times_json = json.dumps(
        [
            scheduled_run_time.isoformat()
            for scheduled_run_time in scheduled_run_times
        ],
        ensure_ascii=False,
    )

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO gta6_scheduler_events (
                job_id,
                event_type,
                scheduled_run_time,
                scheduled_run_times,
                observed_at,
                exception,
                traceback_text,
                run_id,
                execution_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id.strip(),
                event_type,
                (
                    scheduled_run_time.isoformat()
                    if scheduled_run_time is not None
                    else None
                ),
                scheduled_run_times_json,
                observed_at.isoformat(),
                exception.strip() if exception is not None else None,
                traceback_text,
                run_id,
                execution_id.strip()
                if execution_id is not None
                else None,
            ),
        )

        connection.commit()

        row = connection.execute(
            """
            SELECT
                id,
                job_id,
                event_type,
                scheduled_run_time,
                scheduled_run_times,
                observed_at,
                exception,
                traceback_text,
                run_id,
                execution_id,
                created_at
            FROM gta6_scheduler_events
            WHERE id = ?
            LIMIT 1
            """,
            (cursor.lastrowid,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                "GTA6 scheduler event was not persisted"
            )

        result = dict(row)

        result["scheduled_run_times"] = json.loads(
            result["scheduled_run_times"] or "[]"
        )

        return result

    finally:
        connection.close()


def list_gta6_scheduler_events(
    *,
    job_id: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Lista eventos do scheduler GTA 6, do mais recente ao mais antigo."""

    if job_id is not None:
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError(
                "job_id must be a non-empty string or None"
            )

    if event_type is not None:
        if event_type not in GTA6_SCHEDULER_EVENT_TYPES:
            raise ValueError(
                "event_type must be one of "
                "EXECUTED, ERROR, MISSED, MAX_INSTANCES, or None"
            )

    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError("limit must be an integer")

    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    connection = get_connection()

    try:
        conditions = []
        parameters: list[Any] = []

        if job_id is not None:
            conditions.append("job_id = ?")
            parameters.append(job_id.strip())

        if event_type is not None:
            conditions.append("event_type = ?")
            parameters.append(event_type)

        where_clause = (
            f"WHERE {' AND '.join(conditions)}"
            if conditions
            else ""
        )

        parameters.append(limit)

        rows = connection.execute(
            f"""
            SELECT
                id,
                job_id,
                event_type,
                scheduled_run_time,
                scheduled_run_times,
                observed_at,
                exception,
                traceback_text,
                run_id,
                execution_id,
                created_at
            FROM gta6_scheduler_events
            {where_clause}
            ORDER BY id DESC
            LIMIT ?
            """,
            parameters,
        ).fetchall()

        result = []

        for row in rows:
            item = dict(row)
            item["scheduled_run_times"] = json.loads(
                item["scheduled_run_times"] or "[]"
            )
            result.append(item)

        return result

    finally:
        connection.close()
