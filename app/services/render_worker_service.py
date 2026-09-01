from app.services.render_executor_service import AbstractRenderExecutor
from app.services.render_orchestration_service import execute_next_render_job


def process_next_render_job(
    executor: AbstractRenderExecutor | None = None,
):
    """
    Processa exatamente um Render Job.

    O Worker delega toda a lógica de seleção,
    transição de estado e execução ao orquestrador.
    """

    return execute_next_render_job(
        executor=executor,
    )
