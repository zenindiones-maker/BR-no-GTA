from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import requests

from app.services.performance_telemetry_service import PerformanceSpan


MAX_TELEGRAM_UPLOAD_BYTES = 50 * 1024 * 1024
TARGET_PROXY_BYTES = 44 * 1024 * 1024
FALLBACK_PROXY_BYTES = 38 * 1024 * 1024


def _single_mp4(root: Path) -> Path:
    matches = sorted(path for path in root.rglob("*.mp4") if path.is_file())
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one rendered MP4, found {len(matches)}")
    return matches[0]


def _duration_seconds(path: Path) -> float:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)["format"]["duration"]
    duration = float(value)
    if duration <= 0:
        raise RuntimeError("render duration must be positive")
    return duration


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _video_bitrate_kbps(
    duration: float,
    target_bytes: int,
    *,
    audio_kbps: int = 48,
) -> int:
    total_kbps = int((target_bytes * 8) / duration / 1000)
    return max(96, min(2500, total_kbps - audio_kbps - 12))


def _encode_proxy(
    source: Path,
    target: Path,
    *,
    duration: float,
    target_bytes: int,
) -> None:
    video_kbps = _video_bitrate_kbps(duration, target_bytes)
    width = 854 if video_kbps >= 180 else 640
    scale = f"scale='min({width},iw)':-2"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            scale,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-profile:v",
            "main",
            "-pix_fmt",
            "yuv420p",
            "-b:v",
            f"{video_kbps}k",
            "-maxrate",
            f"{max(video_kbps + 24, int(video_kbps * 1.12))}k",
            "-bufsize",
            f"{max(256, video_kbps * 2)}k",
            "-c:a",
            "aac",
            "-b:a",
            "48k",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-movflags",
            "+faststart",
            str(target),
        ],
        check=True,
    )


def build_review_proxy(
    source: Path,
    output_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_duration = _duration_seconds(source)
    proxy = output_dir / "telegram-review.mp4"
    _encode_proxy(
        source,
        proxy,
        duration=source_duration,
        target_bytes=TARGET_PROXY_BYTES,
    )
    if proxy.stat().st_size >= MAX_TELEGRAM_UPLOAD_BYTES:
        _encode_proxy(
            source,
            proxy,
            duration=source_duration,
            target_bytes=FALLBACK_PROXY_BYTES,
        )
    size = proxy.stat().st_size
    if size >= MAX_TELEGRAM_UPLOAD_BYTES:
        raise RuntimeError(
            "Telegram review proxy is too large after fallback compression: "
            f"{size} bytes"
        )
    proxy_duration = _duration_seconds(proxy)
    duration_tolerance = max(0.5, source_duration * 0.001)
    if abs(proxy_duration - source_duration) > duration_tolerance:
        raise RuntimeError("Telegram review proxy duration does not match the master")
    return proxy, {
        "duration_seconds": proxy_duration,
        "source_duration_seconds": source_duration,
        "size_bytes": size,
        "sha256": _sha256(proxy),
    }


def _load_upload_result(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("status") != "UPLOADED":
        raise RuntimeError("private-upload result must be UPLOADED before Telegram review")
    if not result.get("publication_id") or not result.get("youtube_url"):
        raise RuntimeError("private-upload result lacks publication_id/youtube_url")
    if result.get("review_ready") is not True:
        raise RuntimeError("private YouTube master is not HD review-ready")
    processing = result.get("youtube_processing")
    if not isinstance(processing, dict):
        raise RuntimeError("private-upload result lacks YouTube processing evidence")
    required = {
        "status": "READY",
        "privacy_status": "private",
        "upload_status": "processed",
        "processing_status": "succeeded",
        "definition": "hd",
    }
    for key, expected in required.items():
        if processing.get(key) != expected:
            raise RuntimeError(f"YouTube review readiness mismatch: {key}")
    return result


def _telegram_send_review_link(
    *,
    token: str,
    chat_id: str,
    caption: str,
    youtube_url: str,
) -> dict[str, Any]:
    keyboard = {
        "inline_keyboard": [
            [{"text": "▶️ Assistir master privado no YouTube", "url": youtube_url}],
            [{"text": "💬 Aprovar ou pedir edição", "url": "https://t.me/Brnogta_bot"}],
        ]
    }
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    with PerformanceSpan(
        "telegram.review_delivery",
        "TELEGRAM_TIME",
        provider="telegram",
        input_size=len(caption.encode("utf-8")),
        metadata={"link_only": True},
    ) as perf:
        response = requests.post(
            endpoint,
            data={
                "chat_id": chat_id,
                "text": caption,
                "reply_markup": json.dumps(keyboard, ensure_ascii=False),
                "disable_web_page_preview": "false",
            },
            timeout=60,
        )
        perf.set(
            network_ms=perf.elapsed_ms(),
            output_size=len(response.content or b""),
            attempt_count=1,
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Telegram review delivery returned HTTP {response.status_code}") from exc
    if not response.ok or not payload.get("ok"):
        description = str(payload.get("description") or "Telegram API failure")[:400]
        raise RuntimeError(f"Telegram review delivery failed: {description}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Telegram review delivery returned no message result")
    return result


def deliver_review(
    *,
    upload_result_file: Path,
    output_dir: Path,
    token: str,
    review_chat_id: str,
    explicit_human_request: bool = False,
    human_request_ref: str = "",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not explicit_human_request or not str(human_request_ref or "").strip():
        review = {
            "status": "BLOCKED",
            "TELEGRAM_SEND": "NO",
            "reason": "EXPLICIT_HUMAN_REQUEST_REQUIRED",
            "boundary": "NO_AUTONOMOUS_NON_SCRIPT_TELEGRAM_PUSH",
        }
        (output_dir / "telegram-review-result.json").write_text(
            json.dumps(review, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return review

    token = token.strip()
    review_chat_id = review_chat_id.strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for video review delivery")
    if not review_chat_id:
        raise RuntimeError("TELEGRAM_REVIEW_CHAT_ID is not configured")

    upload_result = _load_upload_result(upload_result_file)
    publication_id = int(upload_result["publication_id"])
    video_id = upload_result.get("video_id")
    youtube_url = str(upload_result["youtube_url"])
    processing = dict(upload_result["youtube_processing"])
    caption = (
        "🎬 BR NO GTA — VÍDEO PRIVADO PRONTO PARA REVISÃO\n\n"
        "Assista pelo botão abaixo e responda neste grupo com aprovação ou alterações.\n"
        "Nada fica público sem sua aprovação explícita."
    )
    telegram_message = _telegram_send_review_link(
        token=token,
        chat_id=review_chat_id,
        caption=caption,
        youtube_url=youtube_url,
    )
    review = {
        "status": "DELIVERED",
        "publication_id": publication_id,
        "video_id": video_id,
        "review_chat_id": review_chat_id,
        "telegram_message_id": telegram_message.get("message_id"),
        "youtube_url": youtube_url,
        "youtube_processing": processing,
        "review_surface": "YOUTUBE_PRIVATE_HD_MASTER",
        "telegram_transport": "LINK_ONLY_NO_VIDEO_PROXY",
        "human_request_ref": str(human_request_ref),
        "OPERATIONAL_TELEMETRY_PRESENT": "NO",
        "boundary": "EXPLICIT_HUMAN_REQUEST_REVIEW_ONLY_NO_PUBLICATION_AUTHORITY",
    }
    upload_result["telegram_review"] = review
    upload_result_file.write_text(
        json.dumps(upload_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    result_file = output_dir / "telegram-review-result.json"
    result_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return review


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload-result", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    review = deliver_review(
        upload_result_file=Path(args.upload_result),
        output_dir=Path(args.output_dir),
        token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        review_chat_id=os.getenv("TELEGRAM_REVIEW_CHAT_ID", ""),
        explicit_human_request=(
            str(os.getenv("TELEGRAM_EXPLICIT_HUMAN_REQUEST") or "").strip().upper()
            == "TRUE"
        ),
        human_request_ref=os.getenv("TELEGRAM_HUMAN_REQUEST_REF", ""),
    )
    if review.get("status") == "BLOCKED":
        print("TELEGRAM_VIDEO_REVIEW=BLOCKED")
        print("TELEGRAM_SEND=NO")
        print("NON_SCRIPT_AUTONOMOUS_PUSH=BLOCKED")
        return 0
    print("TELEGRAM_VIDEO_REVIEW=PASS")
    print("REVIEW_SURFACE=YOUTUBE_PRIVATE_HD_MASTER")
    print("TELEGRAM_TRANSPORT=LINK_ONLY_NO_VIDEO_PROXY")
    print(f"PUBLICATION_ID={review['publication_id']}")
    print(f"TELEGRAM_MESSAGE_ID={review['telegram_message_id']}")
    print("PUBLICATION_AUTHORITY=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
