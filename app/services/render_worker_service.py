from typing import Any

from app.database.render_queue_repository import (
    get_render_job,
    list_render_jobs,
    update_render_job_status,
)


def _validate_render_job(render_job: dict[str, Any]) -> None:
    if not isinstance(render_job, dict) or not render_job:
        raise ValueError("O render job informado é inválido.")

    required_fields = [
        "id",
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
    ]

    for field in required_fields:
        if field not in render_job:
            raise ValueError(
                f"O render job não possui o campo obrigatório: {field}."
            )

    if render_job["job_type"] != "video_render":
        raise ValueError("O render job possui tipo inválido.")

    if render_job["queue"] != "render":
        raise ValueError("O render job pertence a uma fila inválida.")

    if render_job["status"] not in {
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
    }:
        raise ValueError("O render job possui status inválido.")

    if not isinstance(render_job["scenes"], list) or not render_job["scenes"]:
        raise ValueError("O render job precisa possuir cenas.")


def get_next_render_job() -> dict[str, Any] | None:
    """Retorna o próximo Render Job disponível para processamento."""

    jobs = list_render_jobs()

    for job in jobs:
        if job.get("status") == "queued":
            return job

    return None


def start_render_job(render_job_id: int) -> bool:
    """Marca um Render Job como em execução."""

    job = get_render_job(render_job_id)

    if job is None:
        return False

    _validate_render_job(job)

    if job["status"] != "queued":
        raise ValueError(
            "O render job precisa estar em estado queued para iniciar."
        )

    return update_render_job_status(render_job_id, "running")


def complete_render_job(render_job_id: int) -> bool:
    """Marca um Render Job como concluído."""

    job = get_render_job(render_job_id)

    if job is None:
        return False

    _validate_render_job(job)

    if job["status"] != "running":
        raise ValueError(
            "O render job precisa estar em estado running para concluir."
        )

    return update_render_job_status(render_job_id, "completed")


def fail_render_job(render_job_id: int) -> bool:
    """Marca um Render Job como falho."""

    job = get_render_job(render_job_id)

    if job is None:
        return False

    _validate_render_job(job)

    if job["status"] != "running":
        raise ValueError(
            "O render job precisa estar em estado running para falhar."
        )

    return update_render_job_status(render_job_id, "failed")


def process_next_render_job(
    render_job: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Processa a próxima unidade de trabalho da fila.

    Esta camada ainda não executa FFmpeg ou outro engine.
    Ela apenas valida o Render Job e controla sua transição
    inicial para running.
    """

    if render_job is not None:
        _validate_render_job(render_job)

        if render_job["status"] != "queued":
            raise ValueError(
                "O render job precisa estar em estado queued para processamento."
            )

        if render_job.get("id") is None:
            raise ValueError("O render job precisa possuir um ID válido.")

        start_render_job(render_job["id"])

        processed_job = get_render_job(render_job["id"])
        return processed_job

    next_job = get_next_render_job()

    if next_job is None:
        return None

    _validate_render_job(next_job)

    start_render_job(next_job["id"])

    return get_render_job(next_job["id"])
