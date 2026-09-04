from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from app.services.script_service import get_script


def build_mpt_task_id(
    render_job_id: int,
    attempt: int,
) -> str:
    """
    Constrói uma identidade determinística de execução compatível
    com o contrato UUID exigido pelo MoneyPrinterTurbo.

    A identidade é derivada exclusivamente de:

        projeto + render_job_id + attempt

    Assim:

        mesmo job + mesma tentativa
            -> mesmo UUID

        mesmo job + tentativa diferente
            -> UUID diferente

        job diferente + mesma tentativa
            -> UUID diferente

    O ID persistido do Render Job permanece inteiro e inalterado.
    """
    if not isinstance(render_job_id, int) or render_job_id <= 0:
        raise ValueError(
            "O render_job_id precisa ser um inteiro positivo."
        )

    if not isinstance(attempt, int) or attempt <= 0:
        raise ValueError(
            "O attempt precisa ser um inteiro positivo."
        )

    identity = (
        f"br-no-gta:render-job:{render_job_id}:attempt:{attempt}"
    )

    task_id = uuid5(NAMESPACE_URL, identity)

    return str(task_id)


def build_mpt_render_request(
    render_job: dict[str, Any],
) -> dict[str, str]:
    """
    Transforma um Render Job persistido no contrato de entrada
    exigido pelo MoneyPrinterTurbo.

    Contrato de saída:
        video_subject
        video_script
        task_id

    Esta camada conhece:
        - o contrato do Render Job;
        - o contrato de entrada do MPT.

    Esta camada não:
        - executa render;
        - acessa GitHub Actions;
        - altera estado do Render Job;
        - publica no YouTube;
        - executa SQLite diretamente.

    O conteúdo do roteiro é resolvido através do Script Service,
    mantendo a persistência fora do executor.

    O task_id do MPT é derivado deterministicamente do ID do
    Render Job e da tentativa atual de execução.
    """
    if not isinstance(render_job, dict) or not render_job:
        raise ValueError("O render job informado é inválido.")

    job_id = render_job.get("id")
    objective = render_job.get("objective")
    script_id = render_job.get("script_id")
    attempt = render_job.get("attempt")

    if not isinstance(job_id, int) or job_id <= 0:
        raise ValueError(
            "O render job precisa possuir um id persistido válido."
        )

    if not isinstance(objective, str) or not objective.strip():
        raise ValueError(
            "O render job precisa possuir um objective utilizável."
        )

    if not isinstance(script_id, int) or script_id <= 0:
        raise ValueError(
            "O render job precisa possuir um script_id persistido válido."
        )

    if not isinstance(attempt, int) or attempt <= 0:
        raise ValueError(
            "O render job precisa possuir um attempt positivo válido."
        )

    script = get_script(script_id)

    if script is None:
        raise ValueError(
            f"Script não encontrado para script_id={script_id}."
        )

    content = script.get("content")

    if not isinstance(content, str) or not content.strip():
        raise ValueError(
            f"O script {script_id} não possui conteúdo utilizável."
        )

    return {
        "video_subject": objective.strip(),
        "video_script": content.strip(),
        "task_id": build_mpt_task_id(
            render_job_id=job_id,
            attempt=attempt,
        ),
    }


__all__ = [
    "build_mpt_task_id",
    "build_mpt_render_request",
]
