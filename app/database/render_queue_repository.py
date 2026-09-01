import json
from typing import Any

from app.database.connection import get_connection


VALID_STATUSES = (
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
)


REQUIRED_FIELDS = (
    "content_item_id",
    "script_id",
    "idea_id",
    "objective",
    "format",
    "estimated_duration_seconds",
    "status",
    "scenes",
    "audio_requirements",
    "visual_requirements",
    "render",
    "job_type",
    "queue",
    "attempt",
)


def enqueue_render_job(render_job: dict[str, Any]) -> int:
    """Persiste um Render Job na fila de renderização."""

    if not isinstance(render_job, dict) or not render_job:
        raise ValueError("O render job informado é inválido.")

    for field in REQUIRED_FIELDS:
        if field not in render_job:
            raise ValueError(
                f"O render job não possui o campo obrigatório: {field}."
            )

    status = render_job.get("status")

    if status not in VALID_STATUSES:
        raise ValueError(f"Status inválido para render job: {status}.")

    scenes = render_job.get("scenes")

    if not isinstance(scenes, list) or not scenes:
        raise ValueError("O render job precisa possuir cenas.")

    payload = dict(render_job)

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO render_jobs (
                content_item_id,
                script_id,
                idea_id,
                objective,
                format,
                estimated_duration_seconds,
                status,
                payload,
                job_type,
                queue,
                attempt
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                render_job["content_item_id"],
                render_job["script_id"],
                render_job["idea_id"],
                render_job["objective"],
                render_job["format"],
                render_job["estimated_duration_seconds"],
                status,
                json.dumps(payload, ensure_ascii=False),
                render_job["job_type"],
                render_job["queue"],
                render_job["attempt"],
            ),
        )

        connection.commit()
        return int(cursor.lastrowid)

    finally:
        connection.close()


def _row_to_render_job(row) -> dict[str, Any] | None:
    """Converte uma linha do banco em Render Job."""

    if row is None:
        return None

    job = json.loads(row["payload"])
    job["id"] = row["id"]
    job["status"] = row["status"]

    return job


def get_render_job(
    job_id: int,
) -> dict[str, Any] | None:
    """Retorna um Render Job pelo ID."""

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                status,
                payload
            FROM render_jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()

        return _row_to_render_job(row)

    finally:
        connection.close()


def list_render_jobs() -> list[dict[str, Any]]:
    """Retorna todos os Render Jobs mais antigos primeiro."""

    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                status,
                payload
            FROM render_jobs
            ORDER BY id ASC
            """
        ).fetchall()

        return [
            job
            for row in rows
            if (job := _row_to_render_job(row)) is not None
        ]

    finally:
        connection.close()


def update_render_job_status(
    job_id: int,
    status: str,
) -> bool:
    """Atualiza o status de um Render Job."""

    if status not in VALID_STATUSES:
        raise ValueError(f"Status inválido para render job: {status}.")

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE render_jobs
            SET
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                status,
                job_id,
            ),
        )

        connection.commit()
        return cursor.rowcount > 0

    finally:
        connection.close()
