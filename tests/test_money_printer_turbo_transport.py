import pytest

from app.services.money_printer_turbo_transport import (
    MoneyPrinterTurboTransportResult,
    parse_video_file,
)


def test_transport_result_contains_remote_and_local_paths():
    result = MoneyPrinterTurboTransportResult(
        remote_video_path="/remote/video.mp4",
        local_video_path="/local/video.mp4",
        remote_sha256="a" * 64,
        local_sha256="a" * 64,
        size_bytes=1024,
    )

    assert result.remote_video_path == "/remote/video.mp4"
    assert result.local_video_path == "/local/video.mp4"


def test_parse_video_file_extracts_path():
    stdout = """
MPT iniciado
Render concluído
VIDEO_FILE=/opt/money-printer-turbo/jobs/123/output/final.mp4
"""

    assert (
        parse_video_file(stdout)
        == "/opt/money-printer-turbo/jobs/123/output/final.mp4"
    )


def test_parse_video_file_ignores_empty_value():
    stdout = """
VIDEO_FILE=
INFO renderizando
VIDEO_FILE=/tmp/final.mp4
"""

    assert parse_video_file(stdout) == "/tmp/final.mp4"


def test_parse_video_file_requires_video_file():
    with pytest.raises(
        ValueError,
        match="VIDEO_FILE",
    ):
        parse_video_file("MPT terminou sem resultado")
