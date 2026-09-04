from __future__ import annotations

from typing import Any

from app.database.connection import get_connection


GTA6_MONITOR_RUN_STATUSES = {
    "RUNNING",
    "COMPLETED",
    "ERROR",
}


def create_gta6_monitor_run(
    *,
    status: str,
    started_at: str,
    url: str,
    status_code: int | None = None,
    baseline: bool = False,
    items_found: int = 0,
    items_ingested: int = 0,
    items_duplicated: int = 0,
    error: str | None = None,
) -> dict[str, Any]:
    """Cria uma execução persistida do monitor GTA 6."""

    if status not in GTA6_MONITOR_RUN_STATUSES:
        raise ValueError(
            "status must be one of RUNNING, COMPLETED, ERROR"
        )

    if not isinstance(started_at, str) or not started_at.strip():
        raise ValueError("started_at must be a non-empty string")

    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")

    if status_code is not None:
        if not isinstance(status_code, int) or isinstance(status_code, bool):
            raise ValueError("status_code must be an integer or None")

    if not isinstance(baseline, bool):
        raise ValueError("baseline must be a boolean")

    for field_name, value in (
        ("items_found", items_found),
        ("items_ingested", items_ingested),
        ("items_duplicated", items_duplicated),
    ):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{field_name} must be an integer")
        if value < 0:
            raise ValueError(f"{field_name} must be greater than or equal to zero")

    if error is not None:
        if not isinstance(error, str) or not error.strip():
            raise ValueError("error must be a non-empty string or None")

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO gta6_monitor_runs (
                status,
                started_at,
                url,
                status_code,
                baseline,
                items_found,
                items_ingested,
                items_duplicated,
                error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                status,
                started_at.strip(),
                url.strip(),
                status_code,
                int(baseline),
                items_found,
                items_ingested,
                items_duplicated,
                error.strip() if error is not None else None,
            ),
        )

        connection.commit()

        row = connection.execute(
            """
            SELECT
                id,
                status,
                started_at,
                finished_at,
                url,
                status_code,
                baseline,
                items_found,
                items_ingested,
                items_duplicated,
                error,
                created_at
            FROM gta6_monitor_runs
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                "GTA6 monitor run was not persisted"
            )

        result = dict(row)
        result["baseline"] = bool(result["baseline"])

        return result

    finally:
        connection.close()


def update_gta6_monitor_run(
    *,
    run_id: int,
    status: str,
    finished_at: str | None = None,
    status_code: int | None = None,
    baseline: bool | None = None,
    items_found: int | None = None,
    items_ingested: int | None = None,
    items_duplicated: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Atualiza o resultado de uma execução persistida."""

    if not isinstance(run_id, int) or isinstance(run_id, bool):
        raise ValueError("run_id must be an integer")

    if run_id <= 0:
        raise ValueError("run_id must be greater than zero")

    if status not in GTA6_MONITOR_RUN_STATUSES:
        raise ValueError(
            "status must be one of RUNNING, COMPLETED, ERROR"
        )

    if finished_at is not None:
        if not isinstance(finished_at, str) or not finished_at.strip():
            raise ValueError(
                "finished_at must be a non-empty string or None"
            )

    if status_code is not None:
        if not isinstance(status_code, int) or isinstance(status_code, bool):
            raise ValueError("status_code must be an integer or None")

    if baseline is not None and not isinstance(baseline, bool):
        raise ValueError("baseline must be a boolean or None")

    for field_name, value in (
        ("items_found", items_found),
        ("items_ingested", items_ingested),
        ("items_duplicated", items_duplicated),
    ):
        if value is not None:
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{field_name} must be an integer or None")
            if value < 0:
                raise ValueError(
                    f"{field_name} must be greater than or equal to zero"
                )

    if error is not None:
        if not isinstance(error, str) or not error.strip():
            raise ValueError("error must be a non-empty string or None")

    connection = get_connection()

    try:
        existing = connection.execute(
            """
            SELECT
                id,
                status,
                started_at,
                finished_at,
                url,
                status_code,
                baseline,
                items_found,
                items_ingested,
                items_duplicated,
                error,
                created_at
            FROM gta6_monitor_runs
            WHERE id = ?
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()

        if existing is None:
            raise ValueError(
                f"GTA6 monitor run {run_id} was not found"
            )

        current = dict(existing)

        connection.execute(
            """
            UPDATE gta6_monitor_runs
            SET
                status = ?,
                finished_at = ?,
                status_code = ?,
                baseline = ?,
                items_found = ?,
                items_ingested = ?,
                items_duplicated = ?,
                error = ?
            WHERE id = ?
            """,
            (
                status,
                (
                    finished_at.strip()
                    if finished_at is not None
                    else current["finished_at"]
                ),
                (
                    status_code
                    if status_code is not None
                    else current["status_code"]
                ),
                (
                    int(baseline)
                    if baseline is not None
                    else current["baseline"]
                ),
                (
                    items_found
                    if items_found is not None
                    else current["items_found"]
                ),
                (
                    items_ingested
                    if items_ingested is not None
                    else current["items_ingested"]
                ),
                (
                    items_duplicated
                    if items_duplicated is not None
                    else current["items_duplicated"]
                ),
                (
                    error.strip()
                    if error is not None
                    else current["error"]
                ),
                run_id,
            ),
        )

        connection.commit()

        row = connection.execute(
            """
            SELECT
                id,
                status,
                started_at,
                finished_at,
                url,
                status_code,
                baseline,
                items_found,
                items_ingested,
                items_duplicated,
                error,
                created_at
            FROM gta6_monitor_runs
            WHERE id = ?
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                "GTA6 monitor run disappeared after update"
            )

        result = dict(row)
        result["baseline"] = bool(result["baseline"])

        return result

    finally:
        connection.close()


def get_gta6_monitor_run(
    run_id: int,
) -> dict[str, Any] | None:
    """Retorna uma execução persistida do monitor GTA 6."""

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
                status,
                started_at,
                finished_at,
                url,
                status_code,
                baseline,
                items_found,
                items_ingested,
                items_duplicated,
                error,
                created_at
            FROM gta6_monitor_runs
            WHERE id = ?
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()

        if row is None:
            return None

        result = dict(row)
        result["baseline"] = bool(result["baseline"])

        return result

    finally:
        connection.close()


def list_gta6_monitor_runs(
    *,
    status: str | None = None,
    url: str | None = None,
) -> list[dict[str, Any]]:
    """Lista execuções persistidas do monitor GTA 6."""

    if status is not None and status not in GTA6_MONITOR_RUN_STATUSES:
        raise ValueError(
            "status must be one of RUNNING, COMPLETED, ERROR or None"
        )

    if url is not None:
        if not isinstance(url, str) or not url.strip():
            raise ValueError(
                "url must be a non-empty string or None"
            )

    connection = get_connection()

    try:
        query = """
            SELECT
                id,
                status,
                started_at,
                finished_at,
                url,
                status_code,
                baseline,
                items_found,
                items_ingested,
                items_duplicated,
                error,
                created_at
            FROM gta6_monitor_runs
        """

        conditions: list[str] = []
        parameters: list[Any] = []

        if status is not None:
            conditions.append("status = ?")
            parameters.append(status)

        if url is not None:
            conditions.append("url = ?")
            parameters.append(url.strip())

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY id ASC"

        rows = connection.execute(
            query,
            parameters,
        ).fetchall()

        results = []

        for row in rows:
            result = dict(row)
            result["baseline"] = bool(result["baseline"])
            results.append(result)

        return results

    finally:
        connection.close()
