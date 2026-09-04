from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.services.ssh_money_printer_turbo_transport import (
    SshMoneyPrinterTurboTransport,
)


REMOTE_RUNNER = (
    "/opt/money-printer-turbo/"
    "money_printer_turbo_remote_runner.py"
)


def create_transport() -> SshMoneyPrinterTurboTransport:
    return SshMoneyPrinterTurboTransport(
        host="production.example.com",
        user="mpt",
        remote_root="/opt/money-printer-turbo",
        remote_runner=REMOTE_RUNNER,
        port=2222,
    )


def test_execute_creates_remote_staging_uploads_input_runs_mpt_and_downloads_video(
    tmp_path,
    monkeypatch,
):
    local_input_dir = tmp_path / "input"
    local_input_dir.mkdir()

    (local_input_dir / "job.json").write_text(
        json.dumps(
            {
                "objective": "GTA 6",
            }
        ),
        encoding="utf-8",
    )

    (local_input_dir / "script.txt").write_text(
        "roteiro de teste",
        encoding="utf-8",
    )

    local_output_path = (
        tmp_path / "output" / "video.mp4"
    )

    remote_video_path = (
        "/opt/money-printer-turbo/"
        "jobs/123/output/video.mp4"
    )

    remote_sha256 = "e76f48070f595a05621b294ff8ff6624d5e2182be1c105bed4a549c624b0e90d"

    def fake_run(
        command,
        *,
        check=False,
        capture_output=False,
        text=False,
        timeout=None,
    ):
        if command[0] == "ssh":
            remote_command = command[-1]

            if remote_command.startswith("mkdir -p "):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="",
                    stderr="",
                )

            if (
                "money_printer_turbo_remote_runner.py"
                in remote_command
            ):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=(
                        "MPT_RESULT\n"
                        f"VIDEO_FILE={remote_video_path}\n"
                        "TASK_DIR=/opt/money-printer-turbo/"
                        "storage/tasks/123\n"
                        "LOG_FILE=/tmp/run-123.log\n"
                        "RESULT_FILE=/tmp/mpt-result.json\n"
                    ),
                    stderr="",
                )

            if remote_command.startswith("ffprobe "):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps(
                        {
                            "format": {
                                "format_name": (
                                    "mov,mp4,m4a,3gp,3g2,mj2"
                                ),
                                "duration": "10.0",
                            },
                            "streams": [
                                {
                                    "codec_type": "video",
                                }
                            ],
                        }
                    ),
                    stderr="",
                )

            if remote_command.startswith("sha256sum "):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=(
                        f"{remote_sha256}  "
                        f"{remote_video_path}\n"
                    ),
                    stderr="",
                )

        if command[0] == "rsync":
            destination = command[-1]

            if destination.endswith("/"):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="",
                    stderr="",
                )

            destination_path = Path(destination)

            destination_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            destination_path.write_bytes(
                b"video recebido corretamente"
            )

            return subprocess.CompletedProcess(
                command,
                0,
                stdout="",
                stderr="",
            )

        raise AssertionError(
            f"Comando não tratado pelo mock:\n{command}"
        )

    monkeypatch.setattr(
        "subprocess.run",
        fake_run,
    )

    transport = create_transport()

    result = transport.execute(
        job_id=123,
        local_input_dir=local_input_dir,
        local_output_path=local_output_path,
    )

    assert result.remote_video_path == remote_video_path
    assert result.local_video_path == str(local_output_path)
    assert result.remote_sha256 == remote_sha256
    assert result.local_sha256 == remote_sha256
    assert result.size_bytes > 0

    assert local_output_path.exists()
    assert local_output_path.read_bytes() == (
        b"video recebido corretamente"
    )


def test_execute_rejects_sha256_mismatch_without_publishing_final_file(
    tmp_path,
    monkeypatch,
):
    local_input_dir = tmp_path / "input"
    local_input_dir.mkdir()

    (local_input_dir / "job.json").write_text(
        json.dumps(
            {
                "objective": "GTA 6",
            }
        ),
        encoding="utf-8",
    )

    (local_input_dir / "script.txt").write_text(
        "roteiro de teste",
        encoding="utf-8",
    )

    local_output_path = tmp_path / "video.mp4"

    remote_video_path = (
        "/opt/money-printer-turbo/"
        "jobs/123/output/video.mp4"
    )

    remote_sha256 = "a" * 64

    def fake_run(
        command,
        *,
        check=False,
        capture_output=False,
        text=False,
        timeout=None,
    ):
        if command[0] == "ssh":
            remote_command = command[-1]

            if remote_command.startswith("mkdir -p "):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="",
                    stderr="",
                )

            if (
                "money_printer_turbo_remote_runner.py"
                in remote_command
            ):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=(
                        "MPT_RESULT\n"
                        f"VIDEO_FILE={remote_video_path}\n"
                        "TASK_DIR=/opt/money-printer-turbo/"
                        "storage/tasks/123\n"
                        "LOG_FILE=/tmp/run-123.log\n"
                        "RESULT_FILE=/tmp/mpt-result.json\n"
                    ),
                    stderr="",
                )

            if remote_command.startswith("ffprobe "):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps(
                        {
                            "format": {
                                "format_name": (
                                    "mov,mp4,m4a,3gp,3g2,mj2"
                                ),
                                "duration": "10.0",
                            },
                            "streams": [
                                {
                                    "codec_type": "video",
                                }
                            ],
                        }
                    ),
                    stderr="",
                )

            if remote_command.startswith("sha256sum "):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=(
                        f"{remote_sha256}  "
                        f"{remote_video_path}\n"
                    ),
                    stderr="",
                )

        if command[0] == "rsync":
            destination = command[-1]

            if destination.endswith("/"):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="",
                    stderr="",
                )

            destination_path = Path(destination)

            destination_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            destination_path.write_bytes(
                b"video recebido com hash diferente"
            )

            return subprocess.CompletedProcess(
                command,
                0,
                stdout="",
                stderr="",
            )

        raise AssertionError(
            f"Comando não tratado pelo mock:\n{command}"
        )

    monkeypatch.setattr(
        "subprocess.run",
        fake_run,
    )

    transport = create_transport()

    with pytest.raises(ValueError, match="SHA-256"):
        transport.execute(
            job_id=123,
            local_input_dir=local_input_dir,
            local_output_path=local_output_path,
        )

    assert not local_output_path.exists()

    partial_output = Path(
        f"{local_output_path}.part"
    )

    assert partial_output.exists()
