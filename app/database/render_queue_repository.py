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


VALID_TRANSITIONS = {
    "queued": {"running"},
    "running": {"completed", "failed"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


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
    """Persiste um Render Job na fila."""

    if not isinstance(render_job, dict) or not render_job:
        raise ValueError("O render job informado é inválido.")

    for field in REQUIRED_FIELDS:
        if field not in render_job:
            raise ValueError(
                f"O render job não possui o campo obrigatório: {field}."
            )

    status = render_job.get("status")

    if status not in VALID_STATUSES:
        raise ValueError(
            f"Status inválido para render job: {status}."
        )

    scenes = render_job.get("scenes")

    if not isinstance(scenes, list) or not scenes:
        raise ValueError(
            "O render job precisa possuir cenas."
        )

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


def claim_next_render_job() -> dict[str, Any] | None:
    """
    Reserva atomicamente o próximo Render Job queued.

    Contrato:
        queued -> running

    O attempt é incrementado exatamente uma vez.
    """

    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        row = connection.execute(
            """
            SELECT
                id,
                status,
                payload,
                attempt
            FROM render_jobs
            WHERE status = 'queued'
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()

        if row is None:
            connection.commit()
            return None

        job = json.loads(row["payload"])

        new_attempt = int(row["attempt"]) + 1

        job["id"] = row["id"]
        job["status"] = "running"
        job["attempt"] = new_attempt
        job["output_path"] = None
        job["error"] = None

        cursor = connection.execute(
            """
            UPDATE render_jobs
            SET
                status = 'running',
                payload = ?,
                attempt = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = 'queued'
            """,
            (
                json.dumps(job, ensure_ascii=False),
                new_attempt,
                row["id"],
            ),
        )

        if cursor.rowcount != 1:
            raise ValueError(
                f"Render job {row['id']} sofreu alteração concorrente."
            )

        connection.commit()

        return job

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def transition_render_job(
    job_id: int,
    target_status: str,
    *,
    output_path: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """
    Executa uma transição válida de estado.

    Importante:
        queued -> running NÃO deve mais ser feito aqui pelo
        fluxo normal do worker.

    A reserva do próximo job é responsabilidade exclusiva
    de claim_next_render_job().
    """

    if target_status not in VALID_STATUSES:
        raise ValueError(
            f"Status inválido para render job: {target_status}."
        )

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                status,
                payload,
                attempt
            FROM render_jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()

        if row is None:
            raise ValueError(
                f"Render job não encontrado: {job_id}"
            )

        current_status = row["status"]

        allowed_targets = VALID_TRANSITIONS.get(
            current_status,
            set(),
        )

        if target_status not in allowed_targets:
            raise ValueError(
                f"Transição inválida para render job {job_id}: "
                f"{current_status} -> {target_status}"
            )

        job = json.loads(row["payload"])

        if target_status == "running":
            job["attempt"] = int(row["attempt"]) + 1
            job["output_path"] = None
            job["error"] = None

        elif target_status == "completed":
            if not output_path:
                raise ValueError(
                    "Render job concluído precisa possuir output_path."
                )

            job["output_path"] = output_path
            job["error"] = None

        elif target_status == "failed":
            if not error:
                raise ValueError(
                    "Render job com falha precisa possuir error."
                )

            job["output_path"] = None
            job["error"] = error

        job["status"] = target_status

        new_attempt = int(
            job.get("attempt", row["attempt"])
        )

        cursor = connection.execute(
            """
            UPDATE render_jobs
            SET
                status = ?,
                payload = ?,
                attempt = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = ?
            """,
            (
                target_status,
                json.dumps(job, ensure_ascii=False),
                new_attempt,
                job_id,
                current_status,
            ),
        )

        if cursor.rowcount != 1:
            raise ValueError(
                f"Render job {job_id} sofreu alteração concorrente."
            )

        connection.commit()

        job["id"] = job_id

        return job

    finally:
        connection.close()


def update_render_job_status(
    job_id: int,
    status: str,
) -> bool:
    """
    Compatibilidade controlada.

    A máquina de estados continua sendo respeitada.
    """

    transition_render_job(
        job_id,
        status,
    )

    return True
