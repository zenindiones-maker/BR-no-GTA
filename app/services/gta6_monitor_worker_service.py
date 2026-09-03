from __future__ import annotations

from app.services.gta6_monitor_run_service import (
    run_gta6_monitor_once,
)


def execute_gta6_monitor(
    *,
    timeout: float = 15.0,
):
    """Executa exatamente um ciclo do monitor GTA6.

    O worker não conhece detalhes de HTTP, parsing, ingestão,
    eventos ou persistência. Ele apenas valida a configuração
    operacional e delega o ciclo ao serviço de monitoramento.
    """
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise ValueError("timeout must be a positive number")

    if timeout <= 0:
        raise ValueError("timeout must be a positive number")

    return run_gta6_monitor_once(
        timeout=float(timeout),
    )
