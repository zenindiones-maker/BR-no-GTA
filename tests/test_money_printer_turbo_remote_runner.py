import json
import subprocess
from pathlib import Path

import pytest

from app.services.money_printer_turbo_remote_runner import (
    build_mpt_command,
    copy_video_to_job_output,
    find_video_file,
    load_json,
    load_script,
    parse_mpt_json,
    validate_video_file,
)


def test_load_json_returns_object(tmp_path):
    path = tmp_path / "job.json"

    path.write_text(
        json.dumps({"objective": "GTA 6"}),
        encoding="utf-8",
    )

    assert load_json(path) == {
        "objective": "GTA 6"
    }


def test_load_json_rejects_non_object(tmp_path):
    path = tmp_path / "job.json"

    path.write_text(
        json.dumps(["invalid"]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_json(path)


def test_load_script_returns_content(tmp_path):
    path = tmp_path / "script.txt"

    path.write_text(
        "roteiro de teste",
        encoding="utf-8",
    )

    assert load_script(path) == "roteiro de teste"


def test_load_script_rejects_empty_file(tmp_path):
    path = tmp_path / "script.txt"

    path.write_text(
        "   ",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_script(path)


def test_build_mpt_command_contains_cli_arguments():
    command = build_mpt_command(
        mpt_root=Path("/opt/mpt"),
        task_id="123",
        video_subject="GTA 6",
        video_script="roteiro",
    )

    assert command == [
        "uv",
        "run",
        "python",
        "cli.py",
        "--task-id",
        "123",
        "--video-subject",
        "GTA 6",
        "--video-script",
        "roteiro",
        "--stop-at",
        "end",
    ]


def test_parse_mpt_json_reads_last_json_line():
    stdout = (
        "log qualquer\n"
        '{"video_file": "/tmp/video.mp4"}\n'
    )

    assert parse_mpt_json(stdout) == {
        "video_file": "/tmp/video.mp4"
    }


def test_parse_mpt_json_rejects_missing_json():
    with pytest.raises(ValueError):
        parse_mpt_json(
            "somente logs\n"
        )


def test_find_video_file_supports_nested_result():
    result = {
        "data": {
            "videos": [
                {
                    "path": (
                        "/opt/mpt/storage/tasks/"
                        "123/final-1.mp4"
                    )
                }
            ]
        }
    }

    assert (
        find_video_file(result)
        == "/opt/mpt/storage/tasks/123/final-1.mp4"
    )


def test_find_video_file_rejects_missing_mp4():
    with pytest.raises(ValueError):
        find_video_file(
            {"status": "success"}
        )


def test_validate_video_file_accepts_valid_file(tmp_path):
    job_root = (
        tmp_path / "storage" / "tasks" / "123"
    )
    job_root.mkdir(parents=True)

    video = job_root / "final-1.mp4"
    video.write_bytes(b"video")

    validate_video_file(
        video_file=video,
        job_root=job_root,
    )


def test_validate_video_file_rejects_file_outside_job(
    tmp_path,
):
    job_root = (
        tmp_path / "storage" / "tasks" / "123"
    )
    job_root.mkdir(parents=True)

    video = tmp_path / "outside.mp4"
    video.write_bytes(b"video")

    with pytest.raises(ValueError):
        validate_video_file(
            video_file=video,
            job_root=job_root,
        )


def test_validate_video_file_rejects_relative_path(
    tmp_path,
):
    job_root = (
        tmp_path / "storage" / "tasks" / "123"
    )
    job_root.mkdir(parents=True)

    with pytest.raises(ValueError):
        validate_video_file(
            video_file=Path("video.mp4"),
            job_root=job_root,
        )


def test_validate_video_file_rejects_empty_file(
    tmp_path,
):
    job_root = (
        tmp_path / "storage" / "tasks" / "123"
    )
    job_root.mkdir(parents=True)

    video = job_root / "final-1.mp4"
    video.write_bytes(b"")

    with pytest.raises(ValueError):
        validate_video_file(
            video_file=video,
            job_root=job_root,
        )


def test_copy_video_to_job_output_creates_stable_output(
    tmp_path,
):
    source = tmp_path / "mpt.mp4"

    source.write_bytes(
        b"video produzido pelo MPT"
    )

    output_dir = (
        tmp_path / "jobs" / "123" / "output"
    )

    output = copy_video_to_job_output(
        video_file=source,
        output_dir=output_dir,
    )

    assert output == (
        output_dir / "video.mp4"
    )

    assert output.read_bytes() == (
        b"video produzido pelo MPT"
    )

    assert not (
        output_dir / "video.mp4.part"
    ).exists()


def test_copy_video_to_job_output_overwrites_previous_output(
    tmp_path,
):
    source = tmp_path / "mpt.mp4"
    source.write_bytes(b"novo video")

    output_dir = (
        tmp_path / "jobs" / "123" / "output"
    )
    output_dir.mkdir(parents=True)

    previous = output_dir / "video.mp4"
    previous.write_bytes(b"video antigo")

    output = copy_video_to_job_output(
        video_file=source,
        output_dir=output_dir,
    )

    assert output.read_bytes() == b"novo video"


def test_remote_runner_command_failure_returns_nonzero():
    result = subprocess.CompletedProcess(
        args=["uv"],
        returncode=1,
        stdout="",
        stderr="erro MPT",
    )

    assert result.returncode == 1
    assert result.stderr == "erro MPT"
