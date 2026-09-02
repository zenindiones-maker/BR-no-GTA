from typing import Any

from app.database.render_queue_repository import enqueue_render_job
from app.services.render_job_service import create_render_job


def enqueue_video_render(
    video_execution_spec: dict[str, Any],
    *,
    video_id: int | None = None,
) -> int:
    """
    Transforma uma Video Execution Spec em um Render Job
    e persiste esse job na fila de renderização.

    Esta camada não executa nem renderiza o vídeo.
    Ela apenas conecta a especificação de execução
    ao mecanismo persistente de fila.

    O video_id é contexto opcional de composição:
    quando fornecido, associa o Render Job ao Video persistido.
    """

    if (
        not isinstance(video_execution_spec, dict)
        or not video_execution_spec
    ):
        raise ValueError(
            "O video execution spec informado é inválido."
        )

    if video_id is not None and (
        not isinstance(video_id, int) or video_id <= 0
    ):
        raise ValueError(
            "video_id must be a positive integer."
        )

    render_job = create_render_job(
        video_execution_spec,
        video_id=video_id,
    )

    return enqueue_render_job(render_job)
