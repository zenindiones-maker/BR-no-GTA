from pathlib import Path

import pytest

from app.services.money_printer_turbo_ssh_executor import (
    MoneyPrinterTurboSshExecutor,
)
from app.services.money_printer_turbo_transport import (
    MoneyPrinterTurboTransportResult,
)
from app.services.render_executor_service import (
    RenderExecutionResult,
)


def _render_job() -> dict:
    return {
        "id": 123,
        "content_item_id": 10,
        "script_id": 20,
        "idea_id": 30,
        "objective": "Explicar uma novidade do GTA 6",
        "format": "youtube",
        "estimated_duration_seconds": 60,
        "scenes": [
            {
                "order": 1,
                "narrative_block": "Introdução",
                "narration": "O GTA 6 pode trazer uma grande novidade.",
                "visual_type": "gameplay",
                "visual_description": "Gameplay de GTA 6.",
                "duration_seconds": 10,
                "execution_requirements": [],
            }
        ],
        "audio_requirements": [
            "narração em português brasileiro",
        ],
        "visual_requirements": [
            "16:9",
        ],
        "render": {
            "resolution": "1920x1080",
            "fps": 30,
            "aspect_ratio": "16:9",
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
        },
    }


class FakeTransport:
    def __init__(self) -> None:
        self.calls = []

    def execute(
        self,
        *,
        job_id: int | str,
        local_input_dir: Path,
        local_output_path: Path,
    ) -> MoneyPrinterTurboTransportResult:
        self.calls.append(
            {
                "job_id": job_id,
                "local_input_dir": local_input_dir,
                "local_output_path": local_output_path,
            }
        )

        return MoneyPrinterTurboTransportResult(
            remote_video_path=(
                "/opt/money-printer-turbo/"
                "jobs/123/output/final-1.mp4"
            ),
            local_video_path=str(
                local_output_path
            ),
            remote_sha256="a" * 64,
            local_sha256="a" * 64,
            size_bytes=123456,
        )


class FailingTransport:
    def execute(
        self,
        *,
        job_id: int | str,
        local_input_dir: Path,
        local_output_path: Path,
    ) -> MoneyPrinterTurboTransportResult:
        raise RuntimeError(
            "falha simulada no transporte"
        )


def test_executor_creates_input_package_and_delegates_to_transport(
    tmp_path: Path,
):
    transport = FakeTransport()

    executor = MoneyPrinterTurboSshExecutor(
        transport=transport,
        input_root=tmp_path / "mpt-jobs",
    )

    result = executor.execute(
        _render_job()
    )

    assert isinstance(
        result,
        RenderExecutionResult,
    )

    assert result.success is True
    assert result.output_path == str(
        tmp_path
        / "mpt-jobs"
        / "123"
        / "output.mp4"
    )

    assert len(transport.calls) == 1

    call = transport.calls[0]

    assert call["job_id"] == 123

    assert call["local_input_dir"] == (
        tmp_path
        / "mpt-jobs"
        / "123"
        / "input"
    )

    assert call["local_output_path"] == (
        tmp_path
        / "mpt-jobs"
        / "123"
        / "output.mp4"
    )

    assert (
        call["local_input_dir"]
        / "job.json"
    ).is_file()

    assert (
        call["local_input_dir"]
        / "script.txt"
    ).is_file()

    assert (
        call["local_input_dir"]
        / "scenes.json"
    ).is_file()


def test_executor_converts_transport_failure_to_failed_result(
    tmp_path: Path,
):
    executor = MoneyPrinterTurboSshExecutor(
        transport=FailingTransport(),
        input_root=tmp_path / "mpt-jobs",
    )

    result = executor.execute(
        _render_job()
    )

    assert result.success is False
    assert result.output_path is None
    assert result.error == (
        "falha simulada no transporte"
    )


def test_executor_rejects_missing_job_id(
    tmp_path: Path,
):
    render_job = _render_job()
    del render_job["id"]

    executor = MoneyPrinterTurboSshExecutor(
        transport=FakeTransport(),
        input_root=tmp_path,
    )

    with pytest.raises(
        ValueError,
        match="id válido",
    ):
        executor.execute(render_job)


def test_executor_rejects_invalid_job_id(
    tmp_path: Path,
):
    render_job = _render_job()
    render_job["id"] = 0

    executor = MoneyPrinterTurboSshExecutor(
        transport=FakeTransport(),
        input_root=tmp_path,
    )

    with pytest.raises(
        ValueError,
        match="id válido",
    ):
        executor.execute(render_job)


def test_executor_rejects_invalid_render_job(
    tmp_path: Path,
):
    executor = MoneyPrinterTurboSshExecutor(
        transport=FakeTransport(),
        input_root=tmp_path,
    )

    with pytest.raises(
        ValueError,
        match="render job informado é inválido",
    ):
        executor.execute({})


def test_executor_requires_transport():
    with pytest.raises(
        ValueError,
        match="transport",
    ):
        MoneyPrinterTurboSshExecutor(
            transport=None,
            input_root=Path("/tmp/mpt"),
        )
