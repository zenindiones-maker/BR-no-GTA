from __future__ import annotations

from typing import Any

from app.services.script_service import get_script


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

    O conteúdo do roteiro é resolvido através do
    Script Service, mantendo a persistência fora do executor.
    """
    if not isinstance(render_job, dict) or not render_job:
        raise ValueError("O render job informado é inválido.")

    job_id = render_job.get("id")
    objective = render_job.get("objective")
    script_id = render_job.get("script_id")

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
        "task_id": str(job_id),
    }
