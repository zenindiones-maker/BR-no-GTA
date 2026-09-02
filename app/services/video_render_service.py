from typing import Any

from app.database.render_queue_repository import get_render_job
from app.services.video_execution_service import (
    create_video_execution_spec,
)
from app.services.video_service import create_video
from app.services.render_queue_service import enqueue_video_render


def create_video_and_enqueue_render(
    video_spec: dict[str, Any],
) -> dict[str, Any]:
    """
    Cria um Video persistido e coloca sua execução
    na fila de renderização.

    Responsabilidades:
    1. Criar e persistir o Video.
    2. Obter o video_id persistido.
    3. Criar a Video Execution Spec.
    4. Criar e persistir o Render Job associado ao Video.
    5. Retornar o Video e o Render Job resultantes.

    Esta camada não:
    - executa renderização;
    - chama FFmpeg;
    - executa Render Worker;
    - altera o estado do Video após o render;
    - publica no YouTube;
    - acessa OAuth ou Google API.

    A Video Execution Spec permanece pura e não recebe video_id.
    O video_id é introduzido somente nesta camada de composição.
    """

    if not isinstance(video_spec, dict) or not video_spec:
        raise ValueError(
            "O video spec informado é inválido."
        )

    video = create_video(video_spec)

    video_id = video.get("id")

    if not isinstance(video_id, int) or video_id <= 0:
        raise RuntimeError(
            "Video criado não possui um id persistido válido."
        )

    video_execution_spec = create_video_execution_spec(
        video_spec,
    )

    render_job_id = enqueue_video_render(
        video_execution_spec,
        video_id=video_id,
    )

    render_job = get_render_job(render_job_id)

    if render_job is None:
        raise RuntimeError(
            "Render Job não encontrado após enfileiramento: "
            f"{render_job_id}"
        )

    if render_job.get("video_id") != video_id:
        raise RuntimeError(
            "Render Job não foi associado ao Video criado."
        )

    return {
        "video": video,
        "render_job": render_job,
    }
