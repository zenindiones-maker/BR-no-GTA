from typing import Any

from app.database.render_queue_repository import enqueue_render_job
from app.services.render_job_service import create_render_job


def enqueue_video_render(
    video_execution_spec: dict[str, Any],
) -> int:
    """
    Transforma uma Video Execution Spec em um Render Job
    e persiste esse job na fila de renderização.

    Esta camada não executa nem renderiza o vídeo.
    Ela apenas conecta a especificação de execução
    ao mecanismo persistente de fila.
    """

    if (
        not isinstance(video_execution_spec, dict)
        or not video_execution_spec
    ):
        raise ValueError(
            "O video execution spec informado é inválido."
        )

    render_job = create_render_job(video_execution_spec)

    return enqueue_render_job(render_job)
