from __future__ import annotations

from app.services.money_printer_turbo_client import (
    MoneyPrinterTurboClient,
)
from app.services.money_printer_turbo_executor import (
    MoneyPrinterTurboExecutor,
)
from app.settings import settings


def create_money_printer_turbo_executor() -> (
    MoneyPrinterTurboExecutor | None
):
    """
    Cria o executor do MoneyPrinterTurbo quando configurado.

    O MPT é opcional no ambiente do BR:
    - sem BR_MPT_BASE_URL, retorna None;
    - com BR_MPT_BASE_URL, cria o cliente HTTP e o executor.

    Esta função não faz nenhuma chamada de rede.
    """

    if not settings.MPT_BASE_URL:
        return None

    client = MoneyPrinterTurboClient(
        base_url=settings.MPT_BASE_URL,
        api_key=settings.MPT_API_KEY,
        timeout=settings.MPT_TIMEOUT,
    )

    return MoneyPrinterTurboExecutor(
        client=client,
        poll_interval=settings.MPT_POLL_INTERVAL,
        max_polls=settings.MPT_MAX_POLLS,
    )
