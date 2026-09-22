from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.services.harness_authorization_service import validate_harness_authorization


HUMAN_SURFACE = "telegram_group"
PRIVATE_TELEGRAM_HUMAN_SURFACE = "DISABLED"
SCRIPT_HUMAN_REVIEW_READY = "SCRIPT_HUMAN_REVIEW_READY"
_AUTONOMOUS_ALLOWED_CATEGORY = SCRIPT_HUMAN_REVIEW_READY
_SCRIPT_STATUS_READY = "READY_FOR_HUMAN_REVIEW"
_TELEMETRY_PATTERN = re.compile(
    r"\b(?:RUN_ID|CANDIDATE_ID|EVALUATION_ID|ROUTING_ID|AUTHORIZATION_ID|"
    r"HARNESS_EPISODE|HERMES_(?:MISSION_)?ID|CHECKPOINT|SOURCE_FETCH_COUNT|"
    r"TELEGRAM_MESSAGES_SENT|CONTINUOUS_STATE_RESTORE)\b",
    re.IGNORECASE,
)


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


def _operational_telemetry_present(text: str) -> bool:
    return bool(_TELEMETRY_PATTERN.search(str(text or "")))


def _delivery_contract(
    *,
    category: str,
    deliverable_type: str | None,
    deliverable_status: str | None,
    complete_script_present: bool,
    harness_authorized: bool,
    text: str,
) -> dict[str, Any]:
    normalized_category = str(category or "").strip().upper()
    allowed = (
        normalized_category == _AUTONOMOUS_ALLOWED_CATEGORY
        and str(deliverable_type or "").strip().upper() == "SCRIPT"
        and str(deliverable_status or "").strip().upper() == _SCRIPT_STATUS_READY
        and bool(complete_script_present)
        and bool(harness_authorized)
        and not _operational_telemetry_present(text)
    )
    return {
        "allowed": allowed,
        "category": normalized_category,
        "deliverable_type": str(deliverable_type or "").strip().upper() or None,
        "deliverable_status": str(deliverable_status or "").strip().upper() or None,
        "complete_script_present": bool(complete_script_present),
        "harness_authorized": bool(harness_authorized),
        "operational_telemetry_present": _operational_telemetry_present(text),
    }


def send_harness_message_to_human_group(
    *,
    authorization,
    text: str,
    category: str,
    lineage: dict[str, Any] | None = None,
    deliverable_type: str | None = None,
    deliverable_status: str | None = None,
    complete_script_present: bool = False,
    harness_authorized: bool = False,
) -> dict[str, Any]:
    auth = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"human-surface:{HUMAN_SURFACE}",
    )
    raw_text = str(text or "").strip()
    contract = _delivery_contract(
        category=category,
        deliverable_type=deliverable_type,
        deliverable_status=deliverable_status,
        complete_script_present=complete_script_present,
        harness_authorized=harness_authorized,
        text=raw_text,
    )
    if not contract["allowed"]:
        return {
            "status": "BLOCKED",
            "TELEGRAM_SEND": "NO",
            "authority": auth.authority,
            "human_surface": HUMAN_SURFACE,
            "private_telegram_human_surface": PRIVATE_TELEGRAM_HUMAN_SURFACE,
            "category": contract["category"],
            "delivery_contract": contract,
            "lineage": dict(lineage or {}),
            "fallback_surface": None,
        }

    rendered = _human_readable(raw_text)
    token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for editorial delivery")
    chat_id = configured_human_group_chat_id()
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
            f"Telegram group editorial surface HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Telegram group editorial surface unavailable: {exc.reason}"
        ) from exc
    if not body.get("ok"):
        raise RuntimeError(
            "Telegram group editorial surface rejected message: "
            + str(body.get("description") or "unknown error")
        )
    result = body.get("result") if isinstance(body, dict) else {}
    return {
        "status": "SENT",
        "TELEGRAM_SEND": "YES",
        "authority": auth.authority,
        "human_surface": HUMAN_SURFACE,
        "private_telegram_human_surface": PRIVATE_TELEGRAM_HUMAN_SURFACE,
        "category": contract["category"],
        "telegram_chat_id": chat_id,
        "telegram_message_id": (
            result.get("message_id") if isinstance(result, dict) else None
        ),
        "delivery_contract": contract,
        "lineage": dict(lineage or {}),
        "fallback_surface": None,
    }


def _script_chunks(script: str, *, limit: int = 3300) -> list[str]:
    remaining = str(script or "").strip()
    if not remaining:
        raise ValueError("complete script is required")
    chunks: list[str] = []
    while len(remaining) > limit:
        cut = max(
            remaining.rfind("\n\n", 0, limit),
            remaining.rfind("\n", 0, limit),
            remaining.rfind(" ", 0, limit),
        )
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def deliver_script_human_review_ready(
    *,
    authorization,
    editorial_summary: str,
    evidence_map: str,
    outline: str,
    complete_script: str,
    lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sections = [
        "RESUMO EDITORIAL\n\n" + str(editorial_summary or "").strip(),
        "EVIDENCE MAP\n\n" + str(evidence_map or "").strip(),
        "OUTLINE\n\n" + str(outline or "").strip(),
    ]
    script_chunks = _script_chunks(complete_script)
    total = len(script_chunks)
    sections.extend(
        f"ROTEIRO {index}/{total}\n\n{chunk}"
        for index, chunk in enumerate(script_chunks, start=1)
    )
    if any(not section.strip() for section in sections):
        raise ValueError("all human review sections are required")
    if any(_operational_telemetry_present(section) for section in sections):
        return {
            "status": "BLOCKED",
            "TELEGRAM_SEND": "NO",
            "category": SCRIPT_HUMAN_REVIEW_READY,
            "reason": "OPERATIONAL_TELEMETRY_PRESENT",
        }

    deliveries = []
    for section in sections:
        sent = send_harness_message_to_human_group(
            authorization=authorization,
            text=section,
            category=SCRIPT_HUMAN_REVIEW_READY,
            lineage=lineage,
            deliverable_type="SCRIPT",
            deliverable_status=_SCRIPT_STATUS_READY,
            complete_script_present=True,
            harness_authorized=True,
        )
        if sent.get("status") != "SENT":
            return {
                "status": "BLOCKED",
                "TELEGRAM_SEND": "NO",
                "category": SCRIPT_HUMAN_REVIEW_READY,
                "deliveries": deliveries,
                "blocked": sent,
            }
        deliveries.append(sent)
    return {
        "status": "SENT",
        "TELEGRAM_SEND": "YES",
        "category": SCRIPT_HUMAN_REVIEW_READY,
        "deliverable_type": "SCRIPT",
        "deliverable_status": _SCRIPT_STATUS_READY,
        "complete_script_present": True,
        "harness_authorized": True,
        "OPERATIONAL_TELEMETRY_PRESENT": "NO",
        "messages_sent": len(deliveries),
        "deliveries": deliveries,
    }
