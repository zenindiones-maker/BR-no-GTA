from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests


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
) -> dict[str, Any]:
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
        "🎬 BR NO GTA — MASTER PRIVADO PRONTO PARA REVISÃO\n"
        f"publication_id={publication_id}\n"
        f"video_id={video_id}\n"
        "visibilidade=PRIVADO\n"
        "qualidade=HD PROCESSADA PELO YOUTUBE\n"
        "status=AGUARDANDO SUA ANÁLISE\n\n"
        "Assista pelo botão abaixo. Esta é a cópia privada derivada do mesmo master "
        "QA-passed que poderá ser publicado depois da sua aprovação.\n\n"
        f"✅ Se estiver aprovado: use /pode_postar {publication_id}\n"
        f"✏️ Se precisar edição: envie 'REVISÃO {publication_id}: <alterações profissionais>'.\n\n"
        "REGRA: nada fica público sem aprovação explícita."
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
        "boundary": "REVIEW_ONLY_NO_PUBLICATION_AUTHORITY",
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
    )
    print("TELEGRAM_VIDEO_REVIEW=PASS")
    print("REVIEW_SURFACE=YOUTUBE_PRIVATE_HD_MASTER")
    print("TELEGRAM_TRANSPORT=LINK_ONLY_NO_VIDEO_PROXY")
    print(f"PUBLICATION_ID={review['publication_id']}")
    print(f"TELEGRAM_MESSAGE_ID={review['telegram_message_id']}")
    print("PUBLICATION_AUTHORITY=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
