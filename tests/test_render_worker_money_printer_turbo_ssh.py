from pathlib import Path

from app.services.money_printer_turbo_ssh_executor import (
    MoneyPrinterTurboSshExecutor,
)
from app.services.money_printer_turbo_transport import (
    MoneyPrinterTurboTransportResult,
)
from app.services.render_executor_service import (
    RenderExecutionResult,
)
from app.services import render_worker_service


class FakeTransport:
    def execute(
        self,
        *,
        job_id: int | str,
        local_input_dir: Path,
        local_output_path: Path,
    ) -> MoneyPrinterTurboTransportResult:
        return MoneyPrinterTurboTransportResult(
            remote_video_path=(
                "/production/jobs/321/output/final-1.mp4"
            ),
            local_video_path=str(
                local_output_path
            ),
            remote_sha256="b" * 64,
            local_sha256="b" * 64,
            size_bytes=1000,
        )


def test_money_printer_turbo_ssh_executor_implements_render_executor_contract(
    tmp_path: Path,
):
    executor = MoneyPrinterTurboSshExecutor(
        transport=FakeTransport(),
        input_root=tmp_path / "mpt-jobs",
    )

    assert isinstance(
        executor,
        render_worker_service.AbstractRenderExecutor,
    )


def test_worker_accepts_money_printer_turbo_ssh_executor(
    monkeypatch,
    tmp_path: Path,
):
    executor = MoneyPrinterTurboSshExecutor(
        transport=FakeTransport(),
        input_root=tmp_path / "mpt-jobs",
    )

    expected = RenderExecutionResult(
        success=True,
        output_path=(
            str(
                tmp_path
                / "mpt-jobs"
                / "321"
                / "output.mp4"
            )
        ),
    )

    monkeypatch.setattr(
        render_worker_service,
        "execute_next_render_job",
        lambda executor: expected,
    )

    result = render_worker_service.process_next_render_job(
        executor=executor,
    )

    assert result == expected
