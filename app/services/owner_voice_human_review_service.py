from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Mapping


VOICE_IDENTITY_ID = "BR_OWNER_V1"
_LEGACY_ALLOWED_ACTIONS = {
    "approve": ("APPROVED_PENDING_ACTIVATION", "BLOCKED_PENDING_PROMOTION"),
    "reject_identity": ("REJECTED_IDENTITY", "BLOCKED_REJECTED"),
    "reject_ptbr": ("REJECTED_PTBR", "BLOCKED_REJECTED"),
}
_SINGLE_ALLOWED_ACTIONS = {
    "approve": ("APPROVED_PENDING_PROMOTION", "BLOCKED_PENDING_PROMOTION"),
    "reject_identity": ("REJECTED_IDENTITY", "BLOCKED_REJECTED"),
    "reject_pronunciation": ("REJECTED_PRONUNCIATION", "BLOCKED_REJECTED"),
}
_ALLOWED_VARIANTS = {"A", "B", "C"}


def _default_state_path() -> Path:
    return (
        Path.home()
        / ".local"
        / "state"
        / "br-no-gta"
        / "owner-voice-human-review.json"
    )


def _load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "schema": "OwnerVoiceHumanReviewState/v1",
            "voice_identity_id": VOICE_IDENTITY_ID,
            "history": [],
        }
    if not isinstance(payload, dict):
        return {
            "schema": "OwnerVoiceHumanReviewState/v1",
            "voice_identity_id": VOICE_IDENTITY_ID,
            "history": [],
        }
    history = payload.get("history")
    if not isinstance(history, list):
        payload["history"] = []
    return payload


def _persist_state(path: Path, payload: Mapping[str, Any]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _parse_callback_data(value: str) -> dict[str, Any] | None:
    data = str(value or "").strip()
    if data.startswith("ov2c:"):
        parts=data.split(":")
        if len(parts)!=7:
            raise ValueError("OWNER_VOICE_REVIEW_CALLBACK_INVALID")
        action_codes={
            "a":"approve",
            "i":"reject_identity",
            "p":"reject_pronunciation",
        }
        action=action_codes.get(str(parts[1] or "").strip())
        token=str(parts[2] or "").strip().lower()
        gate=str(parts[3] or "").strip().upper()
        try:
            anchor=int(parts[4])
            pronunciation=(
                []
                if parts[5]=="-"
                else [int(value) for value in parts[5].split(",") if value]
            )
            vice=int(parts[6])
        except ValueError as exc:
            raise ValueError("OWNER_VOICE_REVIEW_CALLBACK_INVALID") from exc
        if (
            action not in _SINGLE_ALLOWED_ACTIONS
            or len(token)!=20
            or any(ch not in "0123456789abcdef" for ch in token)
            or gate not in {"P","F"}
            or anchor<=0
            or len(pronunciation)>2
            or any(value<=0 for value in pronunciation)
            or (vice>0 and vice not in pronunciation)
        ):
            raise ValueError("OWNER_VOICE_REVIEW_CALLBACK_INVALID")
        return {
            "version":"v2c",
            "action":str(action),
            "subject":token,
            "automatic_gates_passed":gate=="P",
            "identity_anchor_telegram_input_id":anchor,
            "pronunciation_reference_telegram_input_ids":pronunciation,
            "vice_city_reference_telegram_input_id":vice if vice>0 else None,
        }

    if data.startswith("ov2:"):
        parts=data.split(":")
        if len(parts)!=3:
            raise ValueError("OWNER_VOICE_REVIEW_CALLBACK_INVALID")
        action=str(parts[1] or "").strip()
        token=str(parts[2] or "").strip().lower()
        if (
            action not in _SINGLE_ALLOWED_ACTIONS
            or len(token)!=20
            or any(ch not in "0123456789abcdef" for ch in token)
        ):
            raise ValueError("OWNER_VOICE_REVIEW_CALLBACK_INVALID")
        return {
            "version":"v2",
            "action":action,
            "subject":token,
        }

    if not data.startswith("ov1:"):
        return None
    parts = data.split(":")
    if len(parts) != 3:
        raise ValueError("OWNER_VOICE_REVIEW_CALLBACK_INVALID")
    action, variant = parts[1], parts[2].upper()
    if action not in _LEGACY_ALLOWED_ACTIONS or variant not in _ALLOWED_VARIANTS:
        raise ValueError("OWNER_VOICE_REVIEW_CALLBACK_INVALID")
    return {
        "version":"v1",
        "action":action,
        "subject":variant,
    }


def process_owner_voice_review_callback(
    *,
    update: Mapping[str, Any],
    allowed_user_id: int,
    allowed_chat_ids: set[int],
    state_path: str | Path | None = None,
    now_epoch: float | None = None,
) -> dict[str, Any] | None:
    callback = update.get("callback_query")
    if not isinstance(callback, Mapping):
        return None

    parsed = _parse_callback_data(str(callback.get("data") or ""))
    if parsed is None:
        return None
    version=str(parsed["version"])
    action=str(parsed["action"])
    subject=str(parsed["subject"])

    sender = callback.get("from")
    message = callback.get("message")
    chat = message.get("chat") if isinstance(message, Mapping) else None
    callback_id = str(callback.get("id") or "").strip()
    if not callback_id or not isinstance(sender, Mapping) or not isinstance(chat, Mapping):
        raise ValueError("OWNER_VOICE_REVIEW_CALLBACK_INVALID")

    user_id = int(sender.get("id") or 0)
    chat_id = int(chat.get("id") or 0)
    message_id = int(message.get("message_id") or 0)
    if user_id != int(allowed_user_id):
        raise PermissionError("OWNER_VOICE_REVIEW_UNAUTHORIZED_USER")
    if chat_id not in {int(value) for value in allowed_chat_ids}:
        raise PermissionError("OWNER_VOICE_REVIEW_UNAUTHORIZED_CHAT")
    if message_id <= 0:
        raise ValueError("OWNER_VOICE_REVIEW_CALLBACK_INVALID")

    path = Path(state_path).expanduser() if state_path is not None else _default_state_path()
    state = _load_state(path)
    history = [
        item for item in state.get("history", [])
        if isinstance(item, dict)
    ]

    existing = next(
        (
            item for item in reversed(history)
            if str(item.get("callback_query_id") or "") == callback_id
        ),
        None,
    )
    if existing is not None:
        return {**existing, "idempotent_replay": True}

    if version in {"v2","v2c"}:
        status,activation=_SINGLE_ALLOWED_ACTIONS[action]
        receipt = {
            "schema":"OwnerVoiceHumanReviewReceipt/v2",
            "voice_identity_id":VOICE_IDENTITY_ID,
            "candidate_mode":"SINGLE_CLONE",
            "review_token":subject,
            "status":status,
            "review_action":action,
            "production_activation":activation,
            "authorized_human":True,
            "production_authority":True,
            "telegram_chat_id":chat_id,
            "telegram_message_id":message_id,
            "callback_query_id":callback_id,
            "recorded_at_epoch":float(now_epoch if now_epoch is not None else time.time()),
            "idempotent_replay":False,
        }
        if version=="v2c":
            receipt.update({
                "lineage_bound":True,
                "automatic_gates_passed":bool(
                    parsed["automatic_gates_passed"]
                ),
                "identity_anchor_telegram_input_id":int(
                    parsed["identity_anchor_telegram_input_id"]
                ),
                "pronunciation_reference_telegram_input_ids":[
                    int(value)
                    for value in parsed["pronunciation_reference_telegram_input_ids"]
                ],
                "vice_city_reference_telegram_input_id":(
                    int(parsed["vice_city_reference_telegram_input_id"])
                    if parsed["vice_city_reference_telegram_input_id"] is not None
                    else None
                ),
            })
        else:
            receipt["lineage_bound"]=False
            receipt["automatic_gates_passed"]=False
    else:
        status,activation=_LEGACY_ALLOWED_ACTIONS[action]
        receipt = {
            "schema":"OwnerVoiceHumanReviewReceipt/v1",
            "voice_identity_id":VOICE_IDENTITY_ID,
            "status":status,
            "variant":subject,
            "review_action":action,
            "production_activation":activation,
            "authorized_human":True,
            "production_authority":False,
            "telegram_chat_id":chat_id,
            "telegram_message_id":message_id,
            "callback_query_id":callback_id,
            "recorded_at_epoch":float(now_epoch if now_epoch is not None else time.time()),
            "idempotent_replay":False,
        }
    history.append(receipt)
    next_state = {
        "schema": "OwnerVoiceHumanReviewState/v1",
        "voice_identity_id": VOICE_IDENTITY_ID,
        "last_decision": receipt,
        "history": history[-100:],
    }
    _persist_state(path, next_state)
    return receipt
