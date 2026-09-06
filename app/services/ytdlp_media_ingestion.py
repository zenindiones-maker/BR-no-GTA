from __future__ import annotations

from pathlib import Path
from typing import Sequence

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from app.services.media_ingestion import (
    IngestionResult,
    IngestionStatus,
)


class YtDlpMediaIngestion:
    """Media ingestion adapter backed by yt-dlp.

    Credentials, cookies and authenticated browser sessions are deliberately
    not supported by this adapter.
    """

    def __init__(
        self,
        *,
        extractor_args: str | None = None,
        js_runtimes: Sequence[str] = ("deno",),
    ) -> None:
        self._extractor_args = extractor_args
        self._js_runtimes = tuple(js_runtimes)

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

        if self._js_runtimes:
            options["js_runtimes"] = {
                runtime: {}
                for runtime in self._js_runtimes
            }

        if self._extractor_args:
            options["extractor_args"] = {
                "youtube": {
                    "player_client": self._extractor_args,
                }
            }

        try:
            with YoutubeDL(options) as ydl:
                ydl.download([source_url])
        except DownloadError as exc:
            reason = _classify_download_error(str(exc))

            return IngestionResult(
                status=reason[0],
                source_url=source_url,
                reason=reason[1],
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
        or "unavailable" in normalized
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
