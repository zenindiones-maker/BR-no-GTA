from pathlib import Path
from unittest.mock import patch

from app.services.media_ingestion import (
    IngestionResult,
    IngestionStatus,
)


def test_cli_returns_zero_when_ingestion_succeeds(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv(
        "SOURCE_URL",
        "https://www.youtube.com/watch?v=test",
    )
    monkeypatch.setenv(
        "MEDIA_OUTPUT_PATH",
        "/tmp/video.mp4",
    )

    result = IngestionResult(
        status=IngestionStatus.DOWNLOAD_OK,
        source_url="https://www.youtube.com/watch?v=test",
        output_path=Path("/tmp/video.mp4"),
    )

    with patch(
        "app.services.media_ingestion_cli.MediaIngestionService.ingest",
        return_value=result,
    ):
        from app.services.media_ingestion_cli import main

        exit_code = main()

    assert exit_code == 0

    output = capsys.readouterr().out

    assert '"status": "DOWNLOAD_OK"' in output
    assert '"output_path": "/tmp/video.mp4"' in output


def test_cli_returns_one_when_ingestion_is_blocked(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv(
        "SOURCE_URL",
        "https://www.youtube.com/watch?v=test",
    )
    monkeypatch.setenv(
        "MEDIA_OUTPUT_PATH",
        "/tmp/video.mp4",
    )

    result = IngestionResult(
        status=IngestionStatus.DOWNLOAD_BLOCKED,
        source_url="https://www.youtube.com/watch?v=test",
        reason="YOUTUBE_PLAYABILITY_LOGIN_REQUIRED",
    )

    with patch(
        "app.services.media_ingestion_cli.MediaIngestionService.ingest",
        return_value=result,
    ):
        from app.services.media_ingestion_cli import main

        exit_code = main()

    assert exit_code == 1

    output = capsys.readouterr().out

    assert '"status": "DOWNLOAD_BLOCKED"' in output
    assert (
        '"reason": "YOUTUBE_PLAYABILITY_LOGIN_REQUIRED"'
        in output
    )


def test_cli_uses_non_secret_infrastructure_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOURCE_URL",
        "https://www.youtube.com/watch?v=test",
    )
    monkeypatch.setenv(
        "MEDIA_OUTPUT_PATH",
        "/tmp/video.mp4",
    )
    monkeypatch.setenv(
        "YTDLP_PLAYER_CLIENT",
        "mweb",
    )
    monkeypatch.setenv(
        "YTDLP_JS_RUNTIME",
        "deno",
    )
    monkeypatch.setenv(
        "YTDLP_PO_TOKEN_BASE_URL",
        "http://127.0.0.1:4416",
    )

    result = IngestionResult(
        status=IngestionStatus.SOURCE_UNAVAILABLE,
        source_url="https://www.youtube.com/watch?v=test",
        reason="SOURCE_UNAVAILABLE",
    )

    with patch(
        "app.services.media_ingestion_cli.MediaIngestionService.ingest",
        return_value=result,
    ):
        from app.services.media_ingestion_cli import main

        exit_code = main()

    assert exit_code == 1
