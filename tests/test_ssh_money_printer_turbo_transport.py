from pathlib import Path

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


def test_ssh_base_command_without_key():
    transport = create_transport()

    command = transport._ssh_base_command()

    assert command == [
        "ssh",
        "-p",
        "2222",
        "-o",
        "ConnectTimeout=30",
        "mpt@production.example.com",
    ]


def test_ssh_base_command_with_key():
    transport = SshMoneyPrinterTurboTransport(
        host="production.example.com",
        user="mpt",
        remote_root="/opt/money-printer-turbo",
        remote_runner=REMOTE_RUNNER,
        port=2222,
        ssh_key="/home/user/.ssh/mpt_ed25519",
    )

    command = transport._ssh_base_command()

    assert command == [
        "ssh",
        "-p",
        "2222",
        "-o",
        "ConnectTimeout=30",
        "-i",
        "/home/user/.ssh/mpt_ed25519",
        "mpt@production.example.com",
    ]


def test_rsync_base_command_without_key():
    transport = create_transport()

    command = transport._rsync_base_command()

    assert command[:5] == [
        "rsync",
        "-a",
        "--partial",
        "--protect-args",
        "-e",
    ]

    assert command[5].startswith("ssh ")
    assert "-p 2222" in command[5]
    assert "ConnectTimeout=30" in command[5]


def test_rsync_base_command_with_key():
    transport = SshMoneyPrinterTurboTransport(
        host="production.example.com",
        user="mpt",
        remote_root="/opt/money-printer-turbo",
        remote_runner=REMOTE_RUNNER,
        port=2222,
        ssh_key="/home/user/.ssh/br_mpt_ed25519",
    )

    command = transport._rsync_base_command()

    assert command[:5] == [
        "rsync",
        "-a",
        "--partial",
        "--protect-args",
        "-e",
    ]

    assert "-i" in command[5]
    assert "/home/user/.ssh/br_mpt_ed25519" in command[5]


def test_remote_runner_is_part_of_remote_command():
    transport = create_transport()

    command = transport._ssh_base_command()

    remote_input_dir = (
        "/opt/money-printer-turbo/"
        "jobs/123/input"
    )

    remote_output_dir = (
        "/opt/money-printer-turbo/"
        "jobs/123/output"
    )

    transport_command = transport._ssh_base_command()

    assert transport_command == command

    transport._run_remote_runner
    assert REMOTE_RUNNER in transport.remote_runner

    assert remote_input_dir.endswith(
        "/jobs/123/input"
    )

    assert remote_output_dir.endswith(
        "/jobs/123/output"
    )


def test_transport_rejects_missing_remote_runner():
    try:
        SshMoneyPrinterTurboTransport(
            host="production.example.com",
            user="mpt",
            remote_root="/opt/money-printer-turbo",
            remote_runner="",
        )
    except ValueError as exc:
        assert "remote_runner" in str(exc)
    else:
        raise AssertionError(
            "O transport deveria rejeitar remote_runner vazio."
        )


def test_remote_video_path_validation_accepts_job_path():
    transport = create_transport()

    transport._validate_remote_video_path(
        Path(
            "/opt/money-printer-turbo/"
            "jobs/123/output/final-1.mp4"
        ),
        "/opt/money-printer-turbo/jobs/123",
    )


def test_remote_video_path_validation_rejects_outside_path():
    transport = create_transport()

    try:
        transport._validate_remote_video_path(
            Path(
                "/tmp/final-1.mp4"
            ),
            "/opt/money-printer-turbo/jobs/123",
        )
    except ValueError as exc:
        assert "fora" in str(exc)
    else:
        raise AssertionError(
            "O transport deveria rejeitar "
            "vídeo fora do staging do job."
        )
