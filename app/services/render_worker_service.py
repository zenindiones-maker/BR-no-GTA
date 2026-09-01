from typing import Any

from app.services.render_executor_service import (
    AbstractRenderExecutor,
    RenderExecutionResult,
)
from app.services.render_orchestration_service import (
    execute_next_render_job,
)


def process_next_render_job(
    executor: AbstractRenderExecutor | None = None,
) -> RenderExecutionResult | None:
    """
    Processa o próximo Render Job disponível.

    O Worker é responsável apenas por:
    - solicitar o próximo job ao orquestrador;
    - fornecer o executor;
    - devolver o resultado.

    A lógica de estados e execução permanece no orchestrator.
    A implementação concreta da engine permanece no executor.
    """

    return execute_next_render_job(executor=executor)
