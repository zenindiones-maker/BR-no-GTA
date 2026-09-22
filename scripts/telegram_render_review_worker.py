from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests

from scripts.telegram_video_review_worker import _sha256, _single_mp4, build_review_proxy


READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"
STANDARD_BOT_API_BASE_URL = "https://api.telegram.org"
STANDARD_BOT_API_MAX_UPLOAD_BYTES = 49_000_000
LOCAL_BOT_API_MAX_UPLOAD_BYTES = 2_000_000_000


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} must contain an object")
    return value


def _telegram_endpoint(*, api_base_url: str, token: str, method: str) -> str:
    return f"{api_base_url.rstrip('/')}/bot{token}/{method}"


def _send_video(*, token: str, chat_id: str, video: Path, caption: str, api_base_url: str) -> dict[str, Any]:
    try:
        with video.open("rb") as handle:
            response = requests.post(
                _telegram_endpoint(api_base_url=api_base_url, token=token, method="sendVideo"),
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


def _send_document(*, token: str, chat_id: str, document: Path, caption: str, api_base_url: str) -> dict[str, Any]:
    try:
        with document.open("rb") as handle:
            response = requests.post(
                _telegram_endpoint(api_base_url=api_base_url, token=token, method="sendDocument"),
                data={"chat_id": chat_id, "caption": caption},
                files={"document": (document.name, handle, "video/mp4")},
                timeout=600,
            )
    except requests.RequestException:
        raise RuntimeError("Telegram master document transport failed") from None
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Telegram master document returned HTTP {response.status_code}") from exc
    if not response.ok or not payload.get("ok"):
        description = str(payload.get("description") or "Telegram API failure")
        description = description.replace(token, "***")[:300]
        raise RuntimeError(f"Telegram master document delivery failed: {description}")
    message = payload.get("result")
    if not isinstance(message, dict) or not isinstance(message.get("message_id"), int):
        raise RuntimeError("Telegram master document returned no message identity")
    return message


def _gate(folder: Path, filename: str, label: str) -> dict[str, Any]:
    result = _load_object(folder / filename)
    if result.get("status") != "PASS":
        raise RuntimeError(f"{label} must be PASS before Telegram delivery")
    return result


def deliver_render_review(
    *,
    artifact_root: Path,
    token: str,
    review_chat_id: str,
    run_id: str,
    explicit_human_request: bool = False,
    human_request_ref: str = "",
) -> dict[str, Any]:
    source = _single_mp4(artifact_root)
    folder = source.parent
    if not explicit_human_request or not str(human_request_ref or "").strip():
        result = {
            "status": "BLOCKED",
            "TELEGRAM_SEND": "NO",
            "reason": "EXPLICIT_HUMAN_REQUEST_REQUIRED",
            "human_request_ref": None,
            "boundary": "NO_AUTONOMOUS_NON_SCRIPT_TELEGRAM_PUSH",
        }
        (folder / "telegram-review.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result

    token = token.strip()
    review_chat_id = review_chat_id.strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for explicitly requested render review")
    if not review_chat_id:
        raise RuntimeError("TELEGRAM_REVIEW_CHAT_ID is required for explicitly requested render review")
    if not run_id.strip():
        raise RuntimeError("GITHUB_RUN_ID is required for render review")
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
        _gate(folder, "no-artificial-padding-qa.json", "NO_PADDING_QA")
        _gate(folder, "audiovisual-qa.json", "AUDIOVISUAL_QA")
        gates.update(EDITORIAL_QA="PASS", VOICE_QA="PASS", EDIT_QA="PASS", NO_PADDING_QA="PASS")
        if branding.get("intro_duration_seconds", 0) <= 0:
            raise RuntimeError("INTRO_QA requires the intact official intro")
        if branding.get("watermark_start_seconds") != branding.get("intro_duration_seconds"):
            raise RuntimeError("WATERMARK_QA requires watermark to start after intro")
        gates.update(INTRO_QA="PASS", WATERMARK_QA="PASS")

    api_base_url = (os.getenv("TELEGRAM_BOT_API_BASE_URL") or STANDARD_BOT_API_BASE_URL).strip()
    max_upload_bytes = (
        LOCAL_BOT_API_MAX_UPLOAD_BYTES
        if api_base_url.rstrip("/") != STANDARD_BOT_API_BASE_URL
        else STANDARD_BOT_API_MAX_UPLOAD_BYTES
    )
    master_size_bytes = source.stat().st_size
    master_transport_available = master_size_bytes <= max_upload_bytes
    proxy = None
    proxy_evidence = None
    if not master_transport_available:
        proxy, proxy_evidence = build_review_proxy(
            source,
            artifact_root.parent / "review-proxy" / str(job.get("execution_id")),
        )
    duration = qa.get("duration_seconds")
    if is_professional:
        review_label = f"VIDEO {product_label} — PRONTO PARA REVISÃO — NÃO PUBLICAR"
        transport_label = (
            "MASTER 1080P SEM RECOMPRESSÃO"
            if master_transport_available
            else "PREVIEW COMPRIMIDO — MASTER PRESERVADO"
        )
        caption = (
            f"{review_label}\n"
            f"Duração: {duration}s\n"
            f"Versão: {product_version}\n"
            f"Arquivo: {transport_label}\n\n"
            "Revise o vídeo e responda neste grupo com aprovação ou alterações."
        )
    else:
        review_label = "BR NO GTA — VÍDEO PRONTO PARA REVISÃO — NÃO PUBLICAR"
        transport_label = (
            "MASTER SEM RECOMPRESSÃO"
            if master_transport_available
            else "PREVIEW COMPRIMIDO — MASTER PRESERVADO"
        )
        caption = (
            f"{review_label}\n"
            f"Arquivo: {transport_label}\n\n"
            "Revise o vídeo e responda neste grupo com aprovação ou alterações."
        )

    if master_transport_available:
        message = _send_document(
            token=token,
            chat_id=review_chat_id,
            document=source,
            caption=caption,
            api_base_url=api_base_url,
        )
        delivery_mode = "MASTER_DOCUMENT_BYTE_IDENTICAL"
        telegram_media = message.get("document") if isinstance(message.get("document"), dict) else {}
    else:
        message = _send_video(
            token=token,
            chat_id=review_chat_id,
            video=proxy,
            caption=caption,
            api_base_url=api_base_url,
        )
        delivery_mode = "COMPRESSED_REVIEW_PROXY"
        telegram_media = message.get("video") if isinstance(message.get("video"), dict) else {}
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
        "human_review_state": READY_FOR_HUMAN_REVIEW,
        "review_chat_id": review_chat_id,
        "telegram_message_id": message["message_id"],
        "telegram_media_file_id": telegram_media.get("file_id"),
        "telegram_media_file_unique_id": telegram_media.get("file_unique_id"),
        "delivery_mode": delivery_mode,
        "api_base_url_mode": "LOCAL" if api_base_url.rstrip("/") != STANDARD_BOT_API_BASE_URL else "OFFICIAL",
        "max_upload_bytes": max_upload_bytes,
        "master_size_bytes": master_size_bytes,
        "master_sha256": _sha256(source),
        "master_delivered_byte_identical": master_transport_available,
        "master_transport_blocker": None if master_transport_available else "TELEGRAM_BOT_API_UPLOAD_LIMIT",
        "proxy": proxy_evidence,
        "human_request_ref": str(human_request_ref),
        "OPERATIONAL_TELEMETRY_PRESENT": "NO",
        "boundary": "EXPLICIT_HUMAN_REQUEST_REVIEW_ONLY_NO_PUBLICATION_AUTHORITY",
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
        explicit_human_request=(
            str(os.getenv("TELEGRAM_EXPLICIT_HUMAN_REQUEST") or "").strip().upper()
            == "TRUE"
        ),
        human_request_ref=os.getenv("TELEGRAM_HUMAN_REQUEST_REF", ""),
    )
    if result.get("status") == "BLOCKED":
        print("TELEGRAM_RENDER_REVIEW=BLOCKED")
        print("TELEGRAM_SEND=NO")
        print("NON_SCRIPT_AUTONOMOUS_PUSH=BLOCKED")
        return 0
    print("TELEGRAM_RENDER_REVIEW=PASS")
    print("TELEGRAM_REVIEW_DELIVERY=PASS")
    if result.get("product_label") in {"A", "B"}:
        print(f"VIDEO_{result['product_label']}_TELEGRAM_REVIEW_DELIVERY=PASS")
        print("HUMAN_EDITORIAL_APPROVAL=PENDING")
    print(f"HUMAN_REVIEW_STATE={result['human_review_state']}")
    print(f"TELEGRAM_MESSAGE_ID={result['telegram_message_id']}")
    print(f"TELEGRAM_DELIVERY_MODE={result['delivery_mode']}")
    print(f"MASTER_DELIVERED_BYTE_IDENTICAL={'YES' if result['master_delivered_byte_identical'] else 'NO'}")
    print("PUBLICATION_AUTHORITY=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
