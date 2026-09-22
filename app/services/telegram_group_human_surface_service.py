from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

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

_GENUINE_ARTIFACT_ORIGIN = "EDITORIAL_PIPELINE"
_FORBIDDEN_ARTIFACT_ORIGINS = {
    "TEST",
    "FIXTURE",
    "SYNTHETIC",
    "CANARY",
    "PROOF",
    "VALIDATION",
    "CI",
}
_FORBIDDEN_ARTIFACT_REF_MARKERS = (
    "test",
    "fixture",
    "synthetic",
    "canary",
    "proof",
    "validation",
    "human-interface-validation",
)


def _editorial_lineage_contract(lineage: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(lineage or {})
    artifact_ref = str(data.get("artifact_ref") or "").strip()
    artifact_id = str(
        data.get("editorial_artifact_id")
        or data.get("script_id")
        or ""
    ).strip()
    artifact_kind = str(data.get("artifact_kind") or "").strip().upper()
    artifact_status = str(data.get("artifact_status") or "").strip().upper()
    artifact_origin = str(data.get("artifact_origin") or "").strip().upper()
    content_sha256 = str(data.get("content_sha256") or "").strip().lower()
    artifact_file = str(data.get("artifact_file") or "").strip()
    artifact_real = data.get("artifact_real") is True
    explicitly_non_test = all(
        data.get(key) is not True
        for key in (
            "test_artifact",
            "synthetic",
            "fixture",
            "canary",
            "proof",
            "validation_artifact",
        )
    )
    forbidden_ref = any(
        marker in artifact_ref.casefold()
        for marker in _FORBIDDEN_ARTIFACT_REF_MARKERS
    )
    hash_valid = bool(re.fullmatch(r"[0-9a-f]{64}", content_sha256))
    allowed = (
        bool(artifact_ref)
        and bool(artifact_id)
        and artifact_kind == "SCRIPT"
        and artifact_status == _SCRIPT_STATUS_READY
        and artifact_origin == _GENUINE_ARTIFACT_ORIGIN
        and artifact_origin not in _FORBIDDEN_ARTIFACT_ORIGINS
        and artifact_real
        and explicitly_non_test
        and not forbidden_ref
        and hash_valid
    )
    return {
        "allowed": allowed,
        "artifact_ref": artifact_ref or None,
        "editorial_artifact_id": artifact_id or None,
        "artifact_kind": artifact_kind or None,
        "artifact_status": artifact_status or None,
        "artifact_origin": artifact_origin or None,
        "artifact_real": artifact_real,
        "content_sha256_valid": hash_valid,
        "artifact_file": artifact_file or None,
        "test_artifact": data.get("test_artifact") is True,
        "synthetic": data.get("synthetic") is True,
        "fixture": data.get("fixture") is True,
        "canary": data.get("canary") is True,
        "proof": data.get("proof") is True,
        "validation_artifact": data.get("validation_artifact") is True,
        "forbidden_artifact_ref": forbidden_ref,
    }


def _network_transport(*, token: str, chat_id: int, text: str) -> dict[str, Any]:
    payload = urllib.parse.urlencode({
        "chat_id": str(chat_id),
        "text": text,
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
        "message_id": (
            result.get("message_id") if isinstance(result, dict) else None
        ),
        "transport": "TELEGRAM_NETWORK",
    }


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
    lineage: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_category = str(category or "").strip().upper()
    lineage_contract = _editorial_lineage_contract(lineage)
    allowed = (
        normalized_category == _AUTONOMOUS_ALLOWED_CATEGORY
        and str(deliverable_type or "").strip().upper() == "SCRIPT"
        and str(deliverable_status or "").strip().upper() == _SCRIPT_STATUS_READY
        and bool(complete_script_present)
        and bool(harness_authorized)
        and not _operational_telemetry_present(text)
        and lineage_contract["allowed"]
    )
    return {
        "allowed": allowed,
        "category": normalized_category,
        "deliverable_type": str(deliverable_type or "").strip().upper() or None,
        "deliverable_status": str(deliverable_status or "").strip().upper() or None,
        "complete_script_present": bool(complete_script_present),
        "harness_authorized": bool(harness_authorized),
        "operational_telemetry_present": _operational_telemetry_present(text),
        "editorial_lineage": lineage_contract,
    }


def _verify_real_editorial_artifact_file(
    lineage: dict[str, Any] | None,
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    data = dict(lineage or {})
    raw_path = str(data.get("artifact_file") or "").strip()
    if not raw_path:
        return {
            "valid": False,
            "reason": "MISSING_REAL_EDITORIAL_ARTIFACT_FILE",
        }
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(Path.cwd().resolve())
    except (OSError, ValueError):
        return {
            "valid": False,
            "reason": "EDITORIAL_ARTIFACT_FILE_OUTSIDE_WORKSPACE_OR_MISSING",
        }
    if not resolved.is_file():
        return {
            "valid": False,
            "reason": "EDITORIAL_ARTIFACT_FILE_NOT_FILE",
        }
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    return {
        "valid": digest == expected_sha256,
        "reason": None if digest == expected_sha256 else "EDITORIAL_ARTIFACT_HASH_MISMATCH",
        "artifact_file": str(resolved),
        "artifact_file_sha256": digest,
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
    transport: Callable[..., dict[str, Any]] | None = None,
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
        lineage=lineage,
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
    selected_transport = transport or _network_transport
    if transport is None:
        expected_sha256 = str(
            (lineage or {}).get("content_sha256") or ""
        ).strip().lower()
        artifact_check = _verify_real_editorial_artifact_file(
            lineage,
            expected_sha256=expected_sha256,
        )
        if not artifact_check["valid"]:
            return {
                "status": "BLOCKED",
                "TELEGRAM_SEND": "NO",
                "authority": auth.authority,
                "human_surface": HUMAN_SURFACE,
                "private_telegram_human_surface": PRIVATE_TELEGRAM_HUMAN_SURFACE,
                "category": contract["category"],
                "delivery_contract": contract,
                "artifact_check": artifact_check,
                "lineage": dict(lineage or {}),
                "fallback_surface": None,
            }
        token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required for editorial delivery")
        chat_id = configured_human_group_chat_id()
    else:
        token = ""
        chat_id = int(os.getenv("TELEGRAM_CAPTURE_CHAT_ID", "-1000000000000"))
    transport_result = selected_transport(
        token=token,
        chat_id=chat_id,
        text=rendered,
    )
    message_id = transport_result.get("message_id")
    transport_mode = str(
        transport_result.get("transport")
        or ("CAPTURED" if transport is not None else "TELEGRAM_NETWORK")
    )

    return {
        "status": "SENT",
        "TELEGRAM_SEND": "YES",
        "authority": auth.authority,
        "human_surface": HUMAN_SURFACE,
        "private_telegram_human_surface": PRIVATE_TELEGRAM_HUMAN_SURFACE,
        "category": contract["category"],
        "telegram_chat_id": chat_id,
        "telegram_message_id": message_id,
        "transport_mode": transport_mode,
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
    transport: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    script_text = str(complete_script or "").strip()
    lineage_contract = _editorial_lineage_contract(lineage)
    script_sha256 = hashlib.sha256(script_text.encode("utf-8")).hexdigest()
    if not lineage_contract["allowed"] or script_sha256 != str(
        (lineage or {}).get("content_sha256") or ""
    ).strip().lower():
        return {
            "status": "BLOCKED",
            "TELEGRAM_SEND": "NO",
            "category": SCRIPT_HUMAN_REVIEW_READY,
            "reason": "INVALID_OR_NON_GENUINE_EDITORIAL_LINEAGE",
            "editorial_lineage": lineage_contract,
        }
    if transport is None:
        artifact_check = _verify_real_editorial_artifact_file(
            lineage,
            expected_sha256=script_sha256,
        )
        if not artifact_check["valid"]:
            return {
                "status": "BLOCKED",
                "TELEGRAM_SEND": "NO",
                "category": SCRIPT_HUMAN_REVIEW_READY,
                "reason": artifact_check["reason"],
                "editorial_lineage": lineage_contract,
                "artifact_check": artifact_check,
            }

    sections = [
        "RESUMO EDITORIAL\n\n" + str(editorial_summary or "").strip(),
        "EVIDENCE MAP\n\n" + str(evidence_map or "").strip(),
        "OUTLINE\n\n" + str(outline or "").strip(),
    ]
    script_chunks = _script_chunks(script_text)
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
            transport=transport,
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
