from typing import Any

from app.services.editorial_queue_consumer import (
    process_next_editorial_queue_item,
)
from app.services.render_worker_service import (
    process_next_render_job,
)


def run_execution_cycle() -> dict[str, Any]:
    """
    Executa uma unidade controlada do ciclo operacional do BR.

    Fluxo:

        editorial_queue
             ↓
        editorial consumer
             ↓
        render_queue
             ↓
        render worker
             ↓
        render executor

    O Render Worker é responsável por selecionar o executor
    configurado para o ambiente, incluindo o MoneyPrinterTurbo.

    Este serviço apenas orquestra os workers existentes.

    Não contém:
    - regras editoriais;
    - geração de roteiro;
    - produção de vídeo;
    - execução de render;
    - publicação no YouTube.
    """

    editorial_result = process_next_editorial_queue_item()

    render_result = process_next_render_job()

    return {
        "editorial": editorial_result,
        "render": render_result,
    }
