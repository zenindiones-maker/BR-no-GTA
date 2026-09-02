from app.services.money_printer_turbo_factory import (
    create_money_printer_turbo_executor,
)
from app.services.render_executor_service import AbstractRenderExecutor
from app.services.render_orchestration_service import (
    execute_next_render_job,
)


def process_next_render_job(
    executor: AbstractRenderExecutor | None = None,
):
    """
    Processa exatamente um Render Job.

    Quando um executor é fornecido explicitamente, ele possui
    prioridade e é encaminhado diretamente ao orquestrador.

    Quando nenhum executor é fornecido, o Worker tenta obter
    o executor padrão através da factory do MoneyPrinterTurbo.

    Se o MPT não estiver configurado, a factory retorna None e
    o orquestrador mantém seu comportamento padrão.
    """

    selected_executor = executor

    if selected_executor is None:
        selected_executor = create_money_printer_turbo_executor()

    return execute_next_render_job(
        executor=selected_executor,
    )
