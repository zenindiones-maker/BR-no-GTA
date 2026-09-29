from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Mapping


VOICE_IDENTITY_ID = "BR_OWNER_V1"
_ALLOWED_ACTIONS = {
    "approve": ("APPROVED_PENDING_ACTIVATION", "BLOCKED_PENDING_PROMOTION"),
    "reject_identity": ("REJECTED_IDENTITY", "BLOCKED_REJECTED"),
    "reject_ptbr": ("REJECTED_PTBR", "BLOCKED_REJECTED"),
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


def _parse_callback_data(value: str) -> tuple[str, str] | None:
    data = str(value or "").strip()
    if not data.startswith("ov1:"):
        return None
    parts = data.split(":")
    if len(parts) != 3:
        raise ValueError("OWNER_VOICE_REVIEW_CALLBACK_INVALID")
    action, variant = parts[1], parts[2].upper()
    if action not in _ALLOWED_ACTIONS or variant not in _ALLOWED_VARIANTS:
        raise ValueError("OWNER_VOICE_REVIEW_CALLBACK_INVALID")
    return action, variant


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
    action, variant = parsed

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

    status, activation = _ALLOWED_ACTIONS[action]
    receipt = {
        "schema": "OwnerVoiceHumanReviewReceipt/v1",
        "voice_identity_id": VOICE_IDENTITY_ID,
        "status": status,
        "variant": variant,
        "review_action": action,
        "production_activation": activation,
        "authorized_human": True,
        "telegram_chat_id": chat_id,
        "telegram_message_id": message_id,
        "callback_query_id": callback_id,
        "recorded_at_epoch": float(now_epoch if now_epoch is not None else time.time()),
        "idempotent_replay": False,
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
