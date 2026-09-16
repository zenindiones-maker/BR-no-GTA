from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests

from scripts.telegram_video_review_worker import _sha256, _single_mp4, build_review_proxy


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} must contain an object")
    return value


def _send_video(*, token: str, chat_id: str, video: Path, caption: str) -> dict[str, Any]:
    try:
        with video.open("rb") as handle:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendVideo",
                data={"chat_id": chat_id, "caption": caption, "supports_streaming": "true"},
                files={"video": (video.name, handle, "video/mp4")},
                timeout=180,
            )
    except requests.RequestException:
        raise RuntimeError("Telegram render review transport failed") from None
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Telegram render review returned HTTP {response.status_code}") from exc
    if not response.ok or not payload.get("ok"):
        description = str(payload.get("description") or "Telegram API failure")
        description = description.replace(token, "***")[:300]
        raise RuntimeError(f"Telegram render review delivery failed: {description}")
    message = payload.get("result")
    if not isinstance(message, dict) or not isinstance(message.get("message_id"), int):
        raise RuntimeError("Telegram render review returned no message identity")
    return message


def _gate(folder: Path, filename: str, label: str) -> dict[str, Any]:
    result = _load_object(folder / filename)
    if result.get("status") != "PASS":
        raise RuntimeError(f"{label} must be PASS before Telegram delivery")
    return result


def deliver_render_review(*, artifact_root: Path, token: str, review_chat_id: str, run_id: str) -> dict[str, Any]:
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
    qa = _gate(folder, "render-qa.json", "AUDIOVISUAL_QA")
    branding = qa.get("branding")
    if not isinstance(branding, dict):
        raise RuntimeError("render QA lacks branding evidence")

    assets = job.get("brand_assets")
    if not isinstance(assets, list):
        raise RuntimeError("RenderJob lacks governed brand assets")
    asset_identity = [(item.get("asset_id"), item.get("asset_type")) for item in assets if isinstance(item, dict)]
    if sorted(asset_identity) != [(1, "intro"), (2, "watermark")]:
        raise RuntimeError("RenderJob must contain official brand asset IDs 1 and 2")

    product_label = job.get("product_label")
    product_version = job.get("product_version")
    is_professional = job.get("product_profile") == "professional_ptbr_v1"
    gates: dict[str, str] = {"AUDIOVISUAL_QA": "PASS"}
    if is_professional:
        if product_label not in {"A", "B"}:
            raise RuntimeError("professional review requires VIDEO A/B identity")
        if not isinstance(product_version, str) or not product_version.strip():
            raise RuntimeError("professional review requires product version")
        _gate(folder, "editorial-qa.json", "EDITORIAL_QA")
        _gate(folder, "voice-qa.json", "VOICE_QA")
        _gate(folder, "edit-qa.json", "EDIT_QA")
        _gate(folder, "audiovisual-qa.json", "AUDIOVISUAL_QA")
        gates.update(EDITORIAL_QA="PASS", VOICE_QA="PASS", EDIT_QA="PASS")
        if branding.get("intro_duration_seconds", 0) <= 0:
            raise RuntimeError("INTRO_QA requires the intact official intro")
        if branding.get("watermark_start_seconds") != branding.get("intro_duration_seconds"):
            raise RuntimeError("WATERMARK_QA requires watermark to start after intro")
        gates.update(INTRO_QA="PASS", WATERMARK_QA="PASS")

    proxy, proxy_evidence = build_review_proxy(
        source,
        artifact_root.parent / "review-proxy" / str(job.get("execution_id")),
    )
    duration = qa.get("duration_seconds")
    if is_professional:
        review_label = f"VIDEO {product_label} — REVISÃO — NÃO PUBLICAR"
        gate_lines = "\n".join(f"{name}=PASS" for name in (
            "EDITORIAL_QA", "VOICE_QA", "EDIT_QA", "AUDIOVISUAL_QA", "INTRO_QA", "WATERMARK_QA"
        ))
        caption = (
            f"{review_label}\n"
            f"RenderJob={job.get('render_job_id')}\n"
            f"run_id={run_id}\n"
            f"duração={duration}s\n"
            f"versão={product_version}\n"
            f"{gate_lines}\n"
            "HUMAN_EDITORIAL_APPROVAL=PENDING\n"
            "PUBLICATION_AUTHORITY=NONE"
        )
    else:
        review_label = "BR NO GTA — REVISÃO DE RENDER — NÃO PUBLICAR"
        caption = (
            f"{review_label}\nvideo_id={job.get('video_id')}\nrender_job_id={job.get('render_job_id')}\n"
            f"execution_id={job.get('execution_id')}\nasset_ids=1,2\nrun_id={run_id}\n"
            "status=AGUARDANDO SUA AVALIAÇÃO\nPUBLICATION_AUTHORITY=NONE"
        )

    message = _send_video(token=token, chat_id=review_chat_id, video=proxy, caption=caption)
    telegram_video = message.get("video") if isinstance(message.get("video"), dict) else {}
    result = {
        "status": "DELIVERED",
        "telegram_review_delivery": "PASS",
        "label": review_label,
        "product_label": product_label,
        "product_version": product_version,
        "run_id": run_id,
        "video_id": job.get("video_id"),
        "render_job_id": job.get("render_job_id"),
        "execution_id": job.get("execution_id"),
        "duration_seconds": duration,
        "asset_ids": [1, 2],
        "gates": gates,
        "human_editorial_approval": "PENDING" if is_professional else None,
        "review_chat_id": review_chat_id,
        "telegram_message_id": message["message_id"],
        "telegram_video_file_id": telegram_video.get("file_id"),
        "telegram_video_file_unique_id": telegram_video.get("file_unique_id"),
        "master_sha256": _sha256(source),
        "proxy": proxy_evidence,
        "boundary": "REVIEW_ONLY_NO_PUBLICATION_AUTHORITY",
    }
    (folder / "telegram-review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
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
    print("TELEGRAM_REVIEW_DELIVERY=PASS")
    if result.get("product_label") in {"A", "B"}:
        print(f"VIDEO_{result['product_label']}_TELEGRAM_REVIEW_DELIVERY=PASS")
        print("HUMAN_EDITORIAL_APPROVAL=PENDING")
    print(f"TELEGRAM_MESSAGE_ID={result['telegram_message_id']}")
    print("PUBLICATION_AUTHORITY=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
