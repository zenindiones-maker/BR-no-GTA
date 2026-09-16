from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests

from scripts.telegram_video_review_worker import (
    _sha256,
    _single_mp4,
    build_review_proxy,
)


REVIEW_LABEL = "BR NO GTA — REVISÃO DE RENDER — NÃO PUBLICAR"


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} must contain an object")
    return value


def _send_video(
    *, token: str, chat_id: str, video: Path, caption: str
) -> dict[str, Any]:
    try:
        with video.open("rb") as handle:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendVideo",
                data={
                    "chat_id": chat_id,
                    "caption": caption,
                    "supports_streaming": "true",
                },
                files={"video": (video.name, handle, "video/mp4")},
                timeout=180,
            )
    except requests.RequestException:
        # RequestException may embed the request URL, which contains the bot token.
        raise RuntimeError("Telegram render review transport failed") from None
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Telegram render review returned HTTP {response.status_code}"
        ) from exc
    if not response.ok or not payload.get("ok"):
        description = str(payload.get("description") or "Telegram API failure")
        description = description.replace(token, "***")[:300]
        raise RuntimeError(f"Telegram render review delivery failed: {description}")
    message = payload.get("result")
    if not isinstance(message, dict) or not isinstance(message.get("message_id"), int):
        raise RuntimeError("Telegram render review returned no message identity")
    return message


def deliver_render_review(
    *,
    artifact_root: Path,
    token: str,
    review_chat_id: str,
    run_id: str,
) -> dict[str, Any]:
    token = token.strip()
    review_chat_id = review_chat_id.strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for render review")
    if not review_chat_id:
        raise RuntimeError("TELEGRAM_REVIEW_CHAT_ID is required for render review")
    if not run_id.strip():
        raise RuntimeError("GITHUB_RUN_ID is required for render review")

    source = _single_mp4(artifact_root)
    folder = source.parent
    job = _load_object(folder / "render-job.json")
    qa = _load_object(folder / "render-qa.json")
    if qa.get("status") != "PASS":
        raise RuntimeError("render branding QA must be PASS before Telegram delivery")
    branding = qa.get("branding")
    if not isinstance(branding, dict):
        raise RuntimeError("render QA lacks branding evidence")

    assets = job.get("brand_assets")
    if not isinstance(assets, list):
        raise RuntimeError("RenderJob lacks governed brand assets")
    asset_identity = [
        (item.get("asset_id"), item.get("asset_type"))
        for item in assets
        if isinstance(item, dict)
    ]
    if sorted(asset_identity) != [(1, "intro"), (2, "watermark")]:
        raise RuntimeError("RenderJob must contain official brand asset IDs 1 and 2")
    asset_ids = [1, 2]

    proxy, proxy_evidence = build_review_proxy(
        source,
        artifact_root.parent / "review-proxy" / str(job.get("execution_id")),
    )
    caption = (
        f"{REVIEW_LABEL}\n"
        f"video_id={job.get('video_id')}\n"
        f"render_job_id={job.get('render_job_id')}\n"
        f"execution_id={job.get('execution_id')}\n"
        "asset_ids=1,2\n"
        f"intro={branding.get('intro_duration_seconds')}s\n"
        f"watermark_start={branding.get('watermark_start_seconds')}s\n"
        f"watermark_scale={branding.get('watermark_scale')}\n"
        f"watermark_margin={json.dumps(branding.get('watermark_margin'), separators=(',', ':'))}\n"
        f"watermark_opacity={branding.get('watermark_opacity')}\n"
        f"run_id={run_id}\n"
        "status=AGUARDANDO SUA AVALIAÇÃO\n"
        "PUBLICATION_AUTHORITY=NONE"
    )
    message = _send_video(
        token=token,
        chat_id=review_chat_id,
        video=proxy,
        caption=caption,
    )
    telegram_video = message.get("video") if isinstance(message.get("video"), dict) else {}
    result = {
        "status": "DELIVERED",
        "label": REVIEW_LABEL,
        "run_id": run_id,
        "video_id": job.get("video_id"),
        "render_job_id": job.get("render_job_id"),
        "execution_id": job.get("execution_id"),
        "asset_ids": asset_ids,
        "review_chat_id": review_chat_id,
        "telegram_message_id": message["message_id"],
        "telegram_video_file_id": telegram_video.get("file_id"),
        "telegram_video_file_unique_id": telegram_video.get("file_unique_id"),
        "master_sha256": _sha256(source),
        "proxy": proxy_evidence,
        "boundary": "REVIEW_ONLY_NO_PUBLICATION_AUTHORITY",
    }
    (folder / "telegram-review.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", required=True)
    args = parser.parse_args()
    result = deliver_render_review(
        artifact_root=Path(args.artifact_root),
        token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        review_chat_id=os.getenv("TELEGRAM_REVIEW_CHAT_ID", ""),
        run_id=os.getenv("GITHUB_RUN_ID", ""),
    )
    print("TELEGRAM_RENDER_REVIEW=PASS")
    print(f"TELEGRAM_MESSAGE_ID={result['telegram_message_id']}")
    print("PUBLICATION_AUTHORITY=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
