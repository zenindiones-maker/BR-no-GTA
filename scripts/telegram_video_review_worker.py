from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import requests

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


def _video_bitrate_kbps(duration: float, target_bytes: int, *, audio_kbps: int = 48) -> int:
    total_kbps = int((target_bytes * 8) / duration / 1000)
    return max(96, min(2500, total_kbps - audio_kbps - 12))


def _encode_proxy(source: Path, target: Path, *, duration: float, target_bytes: int) -> None:
    video_kbps = _video_bitrate_kbps(duration, target_bytes)
    width = 854 if video_kbps >= 180 else 640
    scale = f"scale='min({width},iw)':-2"
    command = [
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
    ]
    subprocess.run(command, check=True)


def build_review_proxy(source: Path, output_dir: Path) -> tuple[Path, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    duration = _duration_seconds(source)
    proxy = output_dir / "telegram-review.mp4"
    _encode_proxy(source, proxy, duration=duration, target_bytes=TARGET_PROXY_BYTES)
    if proxy.stat().st_size >= MAX_TELEGRAM_UPLOAD_BYTES:
        _encode_proxy(source, proxy, duration=duration, target_bytes=FALLBACK_PROXY_BYTES)
    size = proxy.stat().st_size
    if size >= MAX_TELEGRAM_UPLOAD_BYTES:
        raise RuntimeError(
            f"Telegram review proxy is too large after fallback compression: {size} bytes"
        )
    return proxy, {
        "duration_seconds": duration,
        "size_bytes": size,
        "sha256": _sha256(proxy),
    }


def _load_upload_result(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("status") != "UPLOADED":
        raise RuntimeError("private-upload result must be UPLOADED before Telegram review")
    if not result.get("publication_id") or not result.get("youtube_url"):
        raise RuntimeError("private-upload result lacks publication_id/youtube_url")
    return result


def _telegram_send_video(
    *,
    token: str,
    chat_id: str,
    proxy: Path,
    caption: str,
    youtube_url: str,
) -> dict[str, Any]:
    keyboard = {
        "inline_keyboard": [
            [{"text": "▶️ Abrir master privado no YouTube", "url": youtube_url}],
            [{"text": "💬 Abrir bot para aprovar ou pedir edição", "url": "https://t.me/Brnogta_bot"}],
        ]
    }
    endpoint = f"https://api.telegram.org/bot{token}/sendVideo"
    with proxy.open("rb") as handle:
        response = requests.post(
            endpoint,
            data={
                "chat_id": chat_id,
                "caption": caption,
                "supports_streaming": "true",
                "reply_markup": json.dumps(keyboard, ensure_ascii=False),
            },
            files={"video": (proxy.name, handle, "video/mp4")},
            timeout=180,
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
    artifact_root: Path,
    upload_result_file: Path,
    output_dir: Path,
    token: str,
    review_chat_id: str,
) -> dict[str, Any]:
    token = token.strip()
    review_chat_id = review_chat_id.strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for video review delivery")
    if not review_chat_id:
        raise RuntimeError("TELEGRAM_REVIEW_CHAT_ID is not configured")

    upload_result = _load_upload_result(upload_result_file)
    source = _single_mp4(artifact_root)
    proxy, proxy_evidence = build_review_proxy(source, output_dir)
    publication_id = int(upload_result["publication_id"])
    video_id = upload_result.get("video_id")
    youtube_url = str(upload_result["youtube_url"])
    caption = (
        "🎬 BR NO GTA — REVISÃO OBRIGATÓRIA\n"
        f"publication_id={publication_id}\n"
        f"video_id={video_id}\n"
        "status=AGUARDANDO SUA ANÁLISE\n\n"
        "Este proxy representa exatamente a versão privada enviada ao YouTube. "
        "Assista antes de autorizar publicação pública.\n\n"
        f"✅ Se estiver aprovado: no bot privado use /pode_postar {publication_id}\n"
        f"✏️ Se precisar edição: envie no bot privado 'REVISÃO {publication_id}: <alterações profissionais>'.\n\n"
        "REGRA: o vídeo não deve ficar público sem sua aprovação explícita."
    )
    telegram_message = _telegram_send_video(
        token=token,
        chat_id=review_chat_id,
        proxy=proxy,
        caption=caption,
        youtube_url=youtube_url,
    )
    video = telegram_message.get("video") if isinstance(telegram_message.get("video"), dict) else {}
    review = {
        "status": "DELIVERED",
        "publication_id": publication_id,
        "video_id": video_id,
        "review_chat_id": review_chat_id,
        "telegram_message_id": telegram_message.get("message_id"),
        "telegram_video_file_id": video.get("file_id"),
        "telegram_video_file_unique_id": video.get("file_unique_id"),
        "youtube_url": youtube_url,
        "proxy": proxy_evidence,
        "boundary": "REVIEW_ONLY_NO_PUBLICATION_AUTHORITY",
    }
    upload_result["telegram_review"] = review
    upload_result_file.write_text(
        json.dumps(upload_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result_file = output_dir / "telegram-review-result.json"
    result_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return review


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--upload-result", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    review = deliver_review(
        artifact_root=Path(args.artifact_root),
        upload_result_file=Path(args.upload_result),
        output_dir=Path(args.output_dir),
        token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        review_chat_id=os.getenv("TELEGRAM_REVIEW_CHAT_ID", ""),
    )
    print("TELEGRAM_VIDEO_REVIEW=PASS")
    print(f"PUBLICATION_ID={review['publication_id']}")
    print(f"TELEGRAM_MESSAGE_ID={review['telegram_message_id']}")
    print("PUBLICATION_AUTHORITY=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
