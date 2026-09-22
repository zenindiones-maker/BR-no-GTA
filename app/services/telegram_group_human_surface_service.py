from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.services.harness_authorization_service import validate_harness_authorization


HUMAN_SURFACE = "telegram_group"
PRIVATE_TELEGRAM_HUMAN_SURFACE = "DISABLED"


def _parse_ids(value: str) -> list[int]:
    result: list[int] = []
    for raw in str(value or "").replace(";", ",").split(","):
        text = raw.strip()
        if not text:
            continue
        try:
            chat_id = int(text)
        except ValueError:
            continue
        if chat_id < 0 and chat_id not in result:
            result.append(chat_id)
    return result


def configured_human_group_chat_id() -> int:
    review = str(os.getenv("TELEGRAM_REVIEW_CHAT_ID") or "").strip()
    candidates = _parse_ids(review)
    if not candidates:
        candidates = _parse_ids(
            str(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS") or "")
        )
    if len(candidates) != 1:
        raise RuntimeError(
            "exactly one Telegram group/supergroup must be configured as human surface"
        )
    return candidates[0]


def _human_readable(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        raise ValueError("human-facing Telegram message is required")
    if value.startswith("{") or value.startswith("["):
        raise ValueError("raw JSON is forbidden on the human Telegram surface")
    return value[:3800]


def send_harness_message_to_human_group(
    *,
    authorization,
    text: str,
    category: str,
    lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    auth = validate_harness_authorization(authorization)
    token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for human escalation")
    chat_id = configured_human_group_chat_id()
    rendered = _human_readable(text)
    payload = urllib.parse.urlencode({
        "chat_id": str(chat_id),
        "text": rendered,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:600]
        raise RuntimeError(
            f"Telegram group human surface HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Telegram group human surface unavailable: {exc.reason}"
        ) from exc
    if not body.get("ok"):
        raise RuntimeError(
            "Telegram group human surface rejected message: "
            + str(body.get("description") or "unknown error")
        )
    result = body.get("result") if isinstance(body, dict) else {}
    return {
        "status": "SENT",
        "authority": auth.authority,
        "human_surface": HUMAN_SURFACE,
        "private_telegram_human_surface": PRIVATE_TELEGRAM_HUMAN_SURFACE,
        "category": str(category or "MESSAGE").upper(),
        "telegram_chat_id": chat_id,
        "telegram_message_id": (
            result.get("message_id") if isinstance(result, dict) else None
        ),
        "lineage": dict(lineage or {}),
        "fallback_surface": None,
    }
