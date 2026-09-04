from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.money_printer_turbo_input import (
    create_money_printer_turbo_input_package,
)
from app.services.money_printer_turbo_transport import (
    MoneyPrinterTurboTransport,
)
from app.services.render_executor_service import (
    AbstractRenderExecutor,
    RenderExecutionResult,
)


class MoneyPrinterTurboSshExecutor(AbstractRenderExecutor):
    """
    Executor de renderização do MoneyPrinterTurbo via SSH/rsync.

    Responsabilidades:

        Render Job
            ↓
        Input Package
            ↓
        Transport
            ↓
        MP4 local

    Este executor não conhece:
    - SQLite;
    - HTTP API do MPT;
    - implementação de SSH;
    - implementação de rsync;
    - detalhes internos do MoneyPrinterTurbo.

    Essas responsabilidades pertencem às respectivas camadas.
    """

    def __init__(
        self,
        transport: MoneyPrinterTurboTransport,
        input_root: Path,
    ) -> None:
        if transport is None:
            raise ValueError(
                "O transport do MoneyPrinterTurbo é obrigatório."
            )

        self._transport = transport
        self._input_root = Path(input_root)

    def execute(
        self,
        render_job: dict[str, Any],
    ) -> RenderExecutionResult:
        """
        Executa um Render Job através do transporte SSH/rsync.

        O resultado segue exclusivamente o contrato
        AbstractRenderExecutor.
        """

        if not isinstance(render_job, dict) or not render_job:
            raise ValueError(
                "O render job informado é inválido."
            )

        job_id = render_job.get("id")

        if not isinstance(job_id, int) or job_id <= 0:
            raise ValueError(
                "O render job precisa possuir um id válido."
            )

        local_input_dir = (
            self._input_root / str(job_id)
        )

        output_path = (
            local_input_dir / "output.mp4"
        )

        try:
            package = (
                create_money_printer_turbo_input_package(
                    render_job,
                    local_input_dir / "input",
                )
            )

            output_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            result = self._transport.execute(
                job_id=job_id,
                local_input_dir=package.directory,
                local_output_path=output_path,
            )

            if result is None:
                raise ValueError(
                    "O transport do MoneyPrinterTurbo "
                    "não retornou resultado."
                )

            if not result.local_video_path:
                raise ValueError(
                    "O transport do MoneyPrinterTurbo "
                    "não informou o caminho local do vídeo."
                )

            return RenderExecutionResult(
                success=True,
                output_path=result.local_video_path,
            )

        except Exception as exc:
            return RenderExecutionResult(
                success=False,
                output_path=None,
                error=str(exc),
            )
