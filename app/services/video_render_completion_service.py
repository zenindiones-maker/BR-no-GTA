from typing import Any

from app.database.video_repository import (
    get_video,
    mark_video_ready,
)
from app.database.render_queue_repository import get_render_job


def complete_video_from_render_job(
    render_job_id: int,
) -> dict[str, Any]:
    """
    Finaliza o ciclo de renderização de um Video.

    Responsabilidades:
    1. Buscar o Render Job persistido.
    2. Confirmar que o Render Job está completed.
    3. Obter o video_id associado.
    4. Obter o output_path produzido pelo render.
    5. Confirmar que o Video existe.
    6. Persistir o file_path no Video.
    7. Marcar o Video como ready.
    8. Retornar o Video persistido.

    Esta camada não:
    - executa renderização;
    - chama FFmpeg;
    - controla a fila;
    - executa o worker;
    - publica no YouTube.
    """

    if (
        not isinstance(render_job_id, int)
        or render_job_id <= 0
    ):
        raise ValueError(
            "render_job_id must be a positive integer."
        )

    render_job = get_render_job(render_job_id)

    if render_job is None:
        raise ValueError(
            f"Render job não encontrado: {render_job_id}"
        )

    if render_job.get("status") != "completed":
        raise ValueError(
            "Render job precisa estar completed: "
            f"{render_job_id}"
        )

    video_id = render_job.get("video_id")

    if (
        not isinstance(video_id, int)
        or video_id <= 0
    ):
        raise ValueError(
            "Render job completed não possui video_id válido."
        )

    output_path = render_job.get("output_path")

    if (
        not isinstance(output_path, str)
        or not output_path.strip()
    ):
        raise ValueError(
            "Render job completed não possui output_path válido."
        )

    video = get_video(video_id)

    if video is None:
        raise ValueError(
            f"Video não encontrado: {video_id}"
        )

    updated_video = mark_video_ready(
        video_id,
        output_path.strip(),
    )

    if not updated_video:
        raise RuntimeError(
            "Falha ao persistir Video como ready: "
            f"{video_id}"
        )

    persisted_video = get_video(video_id)

    if persisted_video is None:
        raise RuntimeError(
            "Video desapareceu após conclusão do render: "
            f"{video_id}"
        )

    return persisted_video
