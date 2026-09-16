from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable


class TelegramBrandAssetMaterializationError(ValueError):
    pass


_ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}


def _telegram_api_call(token: str, method: str, payload: dict[str, Any]) -> Any:
    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        # Never include a URL here: the Telegram Bot download/API URL contains
        # the bot token and must not reach worker logs or artifacts.
        raise TelegramBrandAssetMaterializationError(
            f"Telegram API request failed: {type(exc).__name__}"
        ) from exc
    if not data.get("ok"):
        raise TelegramBrandAssetMaterializationError(
            f"Telegram API rejected {method}: {str(data.get('description') or 'unknown error')[:300]}"
        )
    return data.get("result")


def _download_file(token: str, file_path: str, destination: Path) -> None:
    if not file_path or file_path.startswith("/") or ".." in Path(file_path).parts:
        raise TelegramBrandAssetMaterializationError("Telegram getFile returned unsafe file_path")
    request = urllib.request.Request(
        f"https://api.telegram.org/file/bot{token}/{file_path}",
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response, destination.open("wb") as stream:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                stream.write(chunk)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        destination.unlink(missing_ok=True)
        raise TelegramBrandAssetMaterializationError(
            f"Telegram file download failed: {type(exc).__name__}"
        ) from exc


def _safe_extension(*, file_path: str, file_name: str | None, mime_type: str | None, asset_type: str) -> str:
    candidates = [Path(file_path).suffix.lower()]
    if file_name:
        candidates.append(Path(file_name).suffix.lower())
    if mime_type:
        guessed = mimetypes.guess_extension(mime_type, strict=False)
        if guessed:
            candidates.append(guessed.lower())
    allowed = _ALLOWED_VIDEO_EXTS if asset_type == "intro" else _ALLOWED_IMAGE_EXTS
    for ext in candidates:
        if ext in allowed:
            return ext
    raise TelegramBrandAssetMaterializationError(
        f"Unsupported Telegram {asset_type} media extension"
    )


def _validate_snapshot(item: dict[str, Any]) -> None:
    if not isinstance(item, dict):
        raise TelegramBrandAssetMaterializationError("brand asset snapshot must be an object")
    if item.get("asset_type") not in {"intro", "watermark"}:
        raise TelegramBrandAssetMaterializationError("brand asset type must be intro or watermark")
    for key in ("asset_id", "telegram_file_id", "telegram_file_unique_id"):
        value = item.get(key)
        if key == "asset_id":
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise TelegramBrandAssetMaterializationError("brand asset_id is invalid")
        elif not isinstance(value, str) or not value.strip():
            raise TelegramBrandAssetMaterializationError(f"brand {key} is missing")
    if item.get("remote_verified") is not True:
        raise TelegramBrandAssetMaterializationError("brand asset was not remotely verified at ingress")


def materialize_telegram_brand_assets(
    job: dict[str, Any],
    root: Path,
    *,
    token: str | None = None,
    api_call: Callable[[str, str, dict[str, Any]], Any] | None = None,
    downloader: Callable[[str, str, Path], None] | None = None,
    probe: Callable[[Path], dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    snapshots = job.get("brand_assets") or []
    if not isinstance(snapshots, list):
        raise TelegramBrandAssetMaterializationError("brand_assets must be a list")
    if not snapshots:
        return [], []

    token = (token or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise TelegramBrandAssetMaterializationError(
            "TELEGRAM_BOT_TOKEN is required only on the cloud materialization boundary"
        )
    api_call = api_call or _telegram_api_call
    downloader = downloader or _download_file
    if probe is None:
        from app.workers.audiovisual_worker import probe_video

        probe = probe_video

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    hydrated: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    seen_types: set[str] = set()

    for raw in snapshots:
        _validate_snapshot(raw)
        item = deepcopy(raw)
        asset_type = item["asset_type"]
        if asset_type in seen_types:
            raise TelegramBrandAssetMaterializationError(
                f"RenderJob contains more than one active {asset_type} asset"
            )
        seen_types.add(asset_type)

        remote = api_call(token, "getFile", {"file_id": item["telegram_file_id"]})
        if not isinstance(remote, dict) or not isinstance(remote.get("file_path"), str):
            raise TelegramBrandAssetMaterializationError("Telegram getFile returned no file_path")
        file_path = remote["file_path"]
        ext = _safe_extension(
            file_path=file_path,
            file_name=item.get("file_name"),
            mime_type=item.get("mime_type"),
            asset_type=asset_type,
        )
        key = hashlib.sha256(
            (
                f"{item['asset_id']}\n{item['telegram_file_unique_id']}\n{asset_type}"
            ).encode("utf-8")
        ).hexdigest()
        destination = root / f"{asset_type}-{key[:20]}{ext}"
        if destination.exists():
            raise TelegramBrandAssetMaterializationError("brand asset output collision")
        downloader(token, file_path, destination)
        if not destination.is_file() or destination.stat().st_size <= 0:
            raise TelegramBrandAssetMaterializationError("Telegram brand asset download is empty")

        metadata_size = item.get("file_size")
        if isinstance(metadata_size, int) and metadata_size > 0 and destination.stat().st_size != metadata_size:
            raise TelegramBrandAssetMaterializationError(
                "Telegram brand asset size does not match ingress metadata"
            )

        data = probe(destination)
        streams = data.get("streams", []) if isinstance(data, dict) else []
        video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
        if not video_streams:
            raise TelegramBrandAssetMaterializationError(
                f"Telegram {asset_type} has no visual stream"
            )

        duration: float | None = None
        if asset_type == "intro":
            try:
                duration = float(data.get("format", {}).get("duration"))
            except (TypeError, ValueError):
                duration = None
            if duration is None or not math.isfinite(duration) or duration <= 0:
                raise TelegramBrandAssetMaterializationError("Telegram intro has invalid duration")
            ingress_duration = item.get("duration_seconds")
            if isinstance(ingress_duration, (int, float)) and not isinstance(ingress_duration, bool):
                if math.isfinite(float(ingress_duration)) and abs(duration - float(ingress_duration)) > 1.0:
                    raise TelegramBrandAssetMaterializationError(
                        "Telegram intro duration does not match ingress metadata"
                    )

        with destination.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()

        item["media_path"] = str(destination)
        hydrated.append(item)
        evidence.append(
            {
                "asset_id": item["asset_id"],
                "asset_type": asset_type,
                "telegram_file_unique_id": item["telegram_file_unique_id"],
                "sha256": digest,
                "size_bytes": destination.stat().st_size,
                "duration_seconds": duration,
                "mime_type": item.get("mime_type"),
                "remote_getfile_verified": True,
                "downloaded_in_cloud": True,
            }
        )

    return hydrated, evidence
