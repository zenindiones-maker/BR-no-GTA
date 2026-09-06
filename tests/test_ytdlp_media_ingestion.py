from pathlib import Path
from unittest.mock import patch

from yt_dlp.utils import DownloadError

from app.services.media_ingestion import IngestionStatus
from app.services.ytdlp_media_ingestion import YtDlpMediaIngestion


def test_ytdlp_ingestion_configures_expected_options() -> None:
    provider = YtDlpMediaIngestion(
        extractor_args="mweb",
        js_runtimes=("deno",),
    )

    fake_ydl = patch(
        "app.services.ytdlp_media_ingestion.YoutubeDL"
    )

    with fake_ydl as youtube_dl:
        instance = youtube_dl.return_value.__enter__.return_value
        instance.download.return_value = None

        result = provider.ingest(
            "https://www.youtube.com/watch?v=test",
            Path("workspace/input/test.mp4"),
        )

    assert result.status is IngestionStatus.SOURCE_UNAVAILABLE
    assert result.reason == "DOWNLOAD_COMPLETED_WITHOUT_OUTPUT_FILE"

    options = youtube_dl.call_args.args[0]

    assert options["noplaylist"] is True
    assert options["merge_output_format"] == "mp4"
    assert options["js_runtimes"] == {"deno": {}}
    assert options["extractor_args"] == {
        "youtube": {
            "player_client": "mweb",
        }
    }


def test_ytdlp_ingestion_returns_download_ok_when_output_exists(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "video.mp4"
    output_path.write_bytes(b"fake-media")

    provider = YtDlpMediaIngestion(
        extractor_args="mweb",
        js_runtimes=("deno",),
    )

    with patch(
        "app.services.ytdlp_media_ingestion.YoutubeDL"
    ) as youtube_dl:
        instance = youtube_dl.return_value.__enter__.return_value
        instance.download.return_value = None

        result = provider.ingest(
            "https://www.youtube.com/watch?v=test",
            output_path,
        )

    assert result.status is IngestionStatus.DOWNLOAD_OK
    assert result.output_path == output_path


def test_ytdlp_ingestion_classifies_login_required_as_blocked() -> None:
    provider = YtDlpMediaIngestion()

    with patch(
        "app.services.ytdlp_media_ingestion.YoutubeDL"
    ) as youtube_dl:
        instance = youtube_dl.return_value.__enter__.return_value
        instance.download.side_effect = DownloadError(
            "Sign in to confirm you're not a bot"
        )

        result = provider.ingest(
            "https://www.youtube.com/watch?v=test",
            Path("workspace/input/test.mp4"),
        )

    assert result.status is IngestionStatus.DOWNLOAD_BLOCKED
    assert result.reason == "YOUTUBE_PLAYABILITY_LOGIN_REQUIRED"
