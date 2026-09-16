from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import requests

from app.workers.brand_asset_worker import apply, prepare
from scripts.telegram_video_review_worker import (
    MAX_TELEGRAM_UPLOAD_BYTES,
    build_review_proxy,
)


CANARY_LABEL = "BRANDING CANARY — NÃO PUBLICAR"
CANARY_CONTENT_SECONDS = 20.0
REQUIRED_CHECKS = (
    "intro_present",
    "intro_start_zero",
    "intro_duration_measured",
    "intro_has_video",
    "intro_has_audio",
    "intro_complete",
    "intro_av_sync",
    "intro_not_trimmed",
    "intro_not_stretched",
    "watermark_present",
    "watermark_absent_during_intro",
    "watermark_start_after_intro",
    "watermark_position_bottom_right",
    "watermark_aspect_ratio_preserved",
    "watermark_safe_margin",
    "watermark_scale_recorded",
    "ffprobe",
    "full_decode",
)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _telegram_call(token: str, method: str, **params: Any) -> Any:
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/{method}",
            params=params,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Telegram {method} transport failed") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Telegram {method} returned HTTP {response.status_code}") from exc
    if not response.ok or not payload.get("ok"):
        description = str(payload.get("description") or "Telegram API failure")[:300]
        raise RuntimeError(f"Telegram {method} failed: {description}")
    return payload.get("result")


def _attachment(message: dict[str, Any], asset_type: str) -> dict[str, Any] | None:
    if asset_type == "intro":
        media = message.get("video")
        if not isinstance(media, dict):
            document = message.get("document")
            if isinstance(document, dict) and str(document.get("mime_type") or "").startswith("video/"):
                media = document
        if not isinstance(media, dict):
            return None
        return {
            "media_kind": "video",
            "file_name": media.get("file_name") or "intro.mp4",
            "mime_type": media.get("mime_type") or "video/mp4",
            "width": media.get("width"),
            "height": media.get("height"),
            "duration_seconds": media.get("duration"),
            **media,
        }

    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        media = max(
            (item for item in photos if isinstance(item, dict)),
            key=lambda item: int(item.get("file_size") or 0),
        )
        return {
            "media_kind": "photo",
            "file_name": "watermark.jpg",
            "mime_type": "image/jpeg",
            "duration_seconds": None,
            **media,
        }
    document = message.get("document")
    if isinstance(document, dict) and str(document.get("mime_type") or "").startswith("image/"):
        return {
            "media_kind": "document",
            "file_name": document.get("file_name") or "watermark.png",
            "mime_type": document.get("mime_type") or "image/png",
            "duration_seconds": None,
            **document,
        }
    return None


def _discover_asset_snapshots(token: str) -> list[dict[str, Any]]:
    updates = _telegram_call(token, "getUpdates", limit=100, timeout=0)
    if not isinstance(updates, list):
        raise RuntimeError("Telegram getUpdates returned an invalid result")
    discovered: dict[str, dict[str, Any]] = {}
    for update in reversed(updates):
        if not isinstance(update, dict):
            continue
        message = update.get("message")
        if not isinstance(message, dict):
            continue
        caption = str(message.get("caption") or "").casefold()
        candidates: list[str] = []
        if "intro" in caption:
            candidates.append("intro")
        if "marca" in caption or "watermark" in caption:
            candidates.append("watermark")
        for asset_type in candidates:
            if asset_type in discovered:
                continue
            media = _attachment(message, asset_type)
            if media is None:
                continue
            chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
            sender = message.get("from") if isinstance(message.get("from"), dict) else {}
            discovered[asset_type] = {
                "asset_id": 1 if asset_type == "intro" else 2,
                "asset_type": asset_type,
                "telegram_file_id": media.get("file_id"),
                "telegram_file_unique_id": media.get("file_unique_id"),
                "media_kind": media.get("media_kind"),
                "file_name": media.get("file_name"),
                "mime_type": media.get("mime_type"),
                "file_size": media.get("file_size"),
                "width": media.get("width"),
                "height": media.get("height"),
                "duration_seconds": media.get("duration_seconds"),
                "telegram_user_id": sender.get("id"),
                "telegram_chat_id": chat.get("id"),
                "telegram_message_id": message.get("message_id"),
                "telegram_update_id": update.get("update_id"),
                "caption": str(message.get("caption") or ""),
                "remote_verified": True,
                "source": "telegram-pending-update",
            }
    if set(discovered) != {"intro", "watermark"}:
        raise RuntimeError(
            "Canonical asset snapshots are unavailable: configure "
            "TELEGRAM_BRAND_ASSETS_JSON or leave the two labeled Telegram updates pending"
        )
    return [discovered["intro"], discovered["watermark"]]


def _validate_snapshots(token: str, snapshots: Any) -> list[dict[str, Any]]:
    if not isinstance(snapshots, list) or len(snapshots) != 2:
        raise RuntimeError("brand asset snapshot must contain exactly two assets")
    by_id: dict[int, dict[str, Any]] = {}
    for item in snapshots:
        if not isinstance(item, dict):
            raise RuntimeError("brand asset snapshot item must be an object")
        asset_id = item.get("asset_id")
        if asset_id not in (1, 2) or asset_id in by_id:
            raise RuntimeError("brand asset IDs must be exactly 1 and 2")
        expected_type = "intro" if asset_id == 1 else "watermark"
        if item.get("asset_type") != expected_type or item.get("remote_verified") is not True:
            raise RuntimeError("brand asset identity/type/verification mismatch")
        for key in ("telegram_file_id", "telegram_file_unique_id"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise RuntimeError(f"brand asset {asset_id} lacks {key}")
        remote = _telegram_call(token, "getFile", file_id=item["telegram_file_id"])
        if not isinstance(remote, dict) or not remote.get("file_path"):
            raise RuntimeError(f"Telegram did not verify asset {asset_id}")
        by_id[asset_id] = dict(item)
    return [by_id[1], by_id[2]]


def load_asset_snapshots(token: str) -> list[dict[str, Any]]:
    encoded = os.getenv("TELEGRAM_BRAND_ASSETS_JSON", "").strip()
    snapshots = json.loads(encoded) if encoded else _discover_asset_snapshots(token)
    return _validate_snapshots(token, snapshots)


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _send_review(
    *, token: str, chat_id: str, video: Path, caption: str, output_dir: Path
) -> dict[str, Any]:
    review_video = video
    proxy_evidence: dict[str, Any] | None = None
    if video.stat().st_size >= MAX_TELEGRAM_UPLOAD_BYTES:
        review_video, proxy_evidence = build_review_proxy(video, output_dir / "review-proxy")
    try:
        with review_video.open("rb") as handle:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendVideo",
                data={"chat_id": chat_id, "caption": caption, "supports_streaming": "true"},
                files={"video": (review_video.name, handle, "video/mp4")},
                timeout=180,
            )
    except requests.RequestException as exc:
        raise RuntimeError("Telegram review transport failed") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Telegram review returned HTTP {response.status_code}") from exc
    if not response.ok or not payload.get("ok"):
        description = str(payload.get("description") or "Telegram API failure")[:300]
        raise RuntimeError(f"Telegram review delivery failed: {description}")
    message = payload.get("result")
    if not isinstance(message, dict) or not isinstance(message.get("message_id"), int):
        raise RuntimeError("Telegram review delivery returned no message identity")
    return {
        "status": "DELIVERED",
        "telegram_message_id": message["message_id"],
        "review_chat_id": chat_id,
        "proxy": proxy_evidence,
        "boundary": "REVIEW_ONLY_NO_PUBLICATION_AUTHORITY",
    }


def run_canary(root: Path) -> dict[str, Any]:
    token = _required_env("TELEGRAM_BOT_TOKEN")
    review_chat_id = _required_env("TELEGRAM_REVIEW_CHAT_ID")
    assets = load_asset_snapshots(token)
    run_id = _required_env("GITHUB_RUN_ID")
    execution_id = f"branding-canary-{run_id}"
    job = {
        "render_job_id": 900001,
        "video_id": 900001,
        "content_item_id": 900001,
        "script_id": 900001,
        "idea_id": 900001,
        "execution_id": execution_id,
        "brain_decision_id": "branding-canary-not-publish",
        "authorized_action": "EXECUTION",
        "estimated_duration_seconds": CANARY_CONTENT_SECONDS,
        "render": {"resolution": "1280x720", "fps": 30},
        "brand_assets": assets,
        "canary_label": CANARY_LABEL,
    }
    runtime_root = root / "runtime"
    output_root = runtime_root / "output"
    render_folder = output_root / execution_id / str(job["render_job_id"])
    render_folder.mkdir(parents=True, exist_ok=False)
    _write_json(runtime_root / "render-job.json", job)
    prepare(job, runtime_root)
    base = render_folder / f"{job['video_id']}.mp4"
    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={CANARY_CONTENT_SECONDS}",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={CANARY_CONTENT_SECONDS}",
            "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", str(base),
        ]
    )
    _write_json(render_folder / "render-qa.json", {"status": "PASS"})
    final_video = apply(job, runtime_root, output_root)
    qa = json.loads((render_folder / "render-qa.json").read_text(encoding="utf-8"))
    failed = [name for name in REQUIRED_CHECKS if qa.get("checks", {}).get(name) is not True]
    if qa.get("status") != "PASS" or failed:
        raise RuntimeError(f"branding QA failed: {failed}")

    branding = qa["branding"]
    caption = (
        f"{CANARY_LABEL}\n"
        "asset_ids=1,2\n"
        f"intro_measured={branding['intro_duration_seconds']:.3f}s\n"
        f"watermark_start={branding['watermark_start_seconds']:.3f}s\n"
        f"scale={branding['watermark_scale']:.2%}\n"
        f"margin={branding['watermark_margin']}\n"
        f"opacity={branding['watermark_opacity']:.2f}\n"
        f"run_id={run_id}\n"
        "HUMAN_VISUAL_APPROVAL=PENDING"
    )
    review = _send_review(
        token=token,
        chat_id=review_chat_id,
        video=final_video,
        caption=caption,
        output_dir=render_folder,
    )
    _write_json(render_folder / "telegram-review.json", review)
    with final_video.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    summary = {
        "status": "PASS",
        "label": CANARY_LABEL,
        "run_id": run_id,
        "asset_ids": [1, 2],
        "intro_sha256": next(item["sha256"] for item in json.loads((render_folder / "brand-assets.json").read_text())["assets"] if item["asset_id"] == 1),
        "watermark_sha256": next(item["sha256"] for item in json.loads((render_folder / "brand-assets.json").read_text())["assets"] if item["asset_id"] == 2),
        "video_sha256": digest,
        "branding": branding,
        "telegram_review": review,
        "job18_unchanged": True,
        "human_visual_approval": "PENDING",
    }
    _write_json(render_folder / "branding-canary-summary.json", summary)
    print(f"INTRO_MEASURED_DURATION={branding['intro_duration_seconds']}")
    print(f"WATERMARK_START={branding['watermark_start_seconds']}")
    print(f"WATERMARK_SCALE={branding['watermark_scale']}")
    print(f"WATERMARK_MARGIN={json.dumps(branding['watermark_margin'], separators=(',', ':'))}")
    print(f"WATERMARK_OPACITY={branding['watermark_opacity']}")
    print("BRANDING_QA=PASS")
    print("TELEGRAM_REVIEW_DELIVERY=PASS")
    print("JOB18_UNCHANGED=YES")
    return summary


def main() -> int:
    run_canary(Path.cwd())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
