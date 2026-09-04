from __future__ import annotations

from pathlib import Path

from app import settings
from app.services.money_printer_turbo_ssh_executor import (
    MoneyPrinterTurboSshExecutor,
)
from app.services.ssh_money_printer_turbo_transport import (
    SshMoneyPrinterTurboTransport,
)


def create_money_printer_turbo_executor():
    """
    Cria o executor oficial do MoneyPrinterTurbo.

    Arquitetura:

        BR
         ↓
        SshMoneyPrinterTurboTransport
         ↓
        SSH / rsync
         ↓
        máquina de produção
         ↓
        MoneyPrinterTurbo CLI

    O BR não inicia nem consome API HTTP do MPT.
    """

    if not settings.MPT_SSH_HOST:
        return None

    if not settings.MPT_SSH_USER:
        return None

    if not settings.MPT_SSH_KEY:
        return None

    transport = SshMoneyPrinterTurboTransport(
        host=settings.MPT_SSH_HOST,
        user=settings.MPT_SSH_USER,
        port=settings.MPT_SSH_PORT,
        ssh_key=settings.MPT_SSH_KEY,
        remote_root=settings.MPT_REMOTE_ROOT,
        remote_runner=settings.MPT_REMOTE_RUNNER,
        connect_timeout=settings.MPT_SSH_CONNECT_TIMEOUT,
        command_timeout=settings.MPT_SSH_COMMAND_TIMEOUT,
    )

    input_root = Path(
        settings.MPT_LOCAL_INPUT_ROOT
    )

    return MoneyPrinterTurboSshExecutor(
        transport=transport,
        input_root=input_root,
    )
