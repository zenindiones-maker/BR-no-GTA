from __future__ import annotations

from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from app.services.media_ingestion import (
    IngestionResult,
    IngestionStatus,
)
from app.services.ytdlp_infrastructure import (
    YtDlpInfrastructureConfig,
)


class YtDlpMediaIngestion:
    """Media ingestion adapter backed by yt-dlp.

    Credentials, cookies and authenticated browser sessions are deliberately
    not supported by this adapter.
    """

    def __init__(
        self,
        *,
        infrastructure: YtDlpInfrastructureConfig | None = None,
    ) -> None:
        self._infrastructure = (
            infrastructure or YtDlpInfrastructureConfig()
        )

    def ingest(
        self,
        source_url: str,
        output_path: Path,
    ) -> IngestionResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        options = {
            "quiet": False,
            "no_warnings": False,
            "noplaylist": True,
            "outtmpl": str(output_path.with_suffix(".%(ext)s")),
            "merge_output_format": "mp4",
        }

        infrastructure = self._infrastructure

        if infrastructure.js_runtime:
            options["js_runtimes"] = {
                infrastructure.js_runtime: {},
            }

        extractor_args = {
            "youtube": {
                "player_client": infrastructure.player_client,
            },
        }

        if infrastructure.po_token_base_url:
            extractor_args["youtubepot-bgutilhttp"] = {
                "base_url": infrastructure.po_token_base_url,
            }

        options["extractor_args"] = extractor_args

        try:
            with YoutubeDL(options) as ydl:
                ydl.download([source_url])
        except DownloadError as exc:
            status, reason = _classify_download_error(str(exc))

            return IngestionResult(
                status=status,
                source_url=source_url,
                reason=reason,
            )

        downloaded = _resolve_downloaded_file(output_path)

        if downloaded is None:
            return IngestionResult(
                status=IngestionStatus.SOURCE_UNAVAILABLE,
                source_url=source_url,
                reason="DOWNLOAD_COMPLETED_WITHOUT_OUTPUT_FILE",
            )

        return IngestionResult(
            status=IngestionStatus.DOWNLOAD_OK,
            source_url=source_url,
            output_path=downloaded,
        )


def _resolve_downloaded_file(output_path: Path) -> Path | None:
    if output_path.exists():
        return output_path

    candidates = sorted(
        output_path.parent.glob(
            f"{output_path.stem}.*"
        )
    )

    media_candidates = [
        path
        for path in candidates
        if path.suffix.lower() in {
            ".mp4",
            ".mkv",
            ".webm",
            ".mov",
            ".avi",
        }
    ]

    if not media_candidates:
        return None

    return media_candidates[0]


def _classify_download_error(
    message: str,
) -> tuple[IngestionStatus, str]:
    normalized = message.lower()

    if (
        "login_required" in normalized
        or "sign in to confirm" in normalized
        or "confirm you're not a bot" in normalized
    ):
        return (
            IngestionStatus.DOWNLOAD_BLOCKED,
            "YOUTUBE_PLAYABILITY_LOGIN_REQUIRED",
        )

    if (
        "video unavailable" in normalized
        or "this video is unavailable" in normalized
    ):
        return (
            IngestionStatus.SOURCE_UNAVAILABLE,
            "SOURCE_UNAVAILABLE",
        )

    if (
        "unsupported url" in normalized
        or "no suitable extractor" in normalized
    ):
        return (
            IngestionStatus.SOURCE_UNSUPPORTED,
            "SOURCE_UNSUPPORTED",
        )

    return (
        IngestionStatus.DOWNLOAD_BLOCKED,
        "MEDIA_DOWNLOAD_FAILED",
    )
