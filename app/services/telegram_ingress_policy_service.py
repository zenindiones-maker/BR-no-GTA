from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Mapping


HUMAN_SURFACE = "telegram_group"
PRIVATE_TELEGRAM_HUMAN_SURFACE = "DISABLED"
SUPPORTED_CHAT_TYPES = frozenset({"group", "supergroup"})


@dataclass(frozen=True)
class TelegramIngress:
    user_id: int
    chat_id: int
    chat_type: str
    message: dict[str, Any]
    text: str
    authorized_sender: bool
    authorized_chat: bool

    @property
    def accepted(self) -> bool:
        return bool(self.authorized_sender and self.authorized_chat)


def _parse_ids(value: Any) -> set[int]:
    if value in (None, ""):
        return set()
    raw = value if isinstance(value, (list, tuple, set)) else str(value).replace(";", ",").split(",")
    result: set[int] = set()
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        try:
            identity = int(text)
        except ValueError:
            continue
        if identity != 0:
            result.add(identity)
    return result


def configured_allowed_chat_ids(state: Mapping[str, Any]) -> set[int]:
    allowed = _parse_ids(state.get("allowed_chat_ids"))
    allowed.update(_parse_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")))
    review_chat = os.getenv("TELEGRAM_REVIEW_CHAT_ID", "").strip()
    if review_chat:
        allowed.update(_parse_ids(review_chat))
    # Legacy private pairing state is deliberately ignored. The only human
    # surface is an explicitly allowed Telegram group/supergroup.
    return allowed


def parse_governed_telegram_ingress(
    update: Mapping[str, Any],
    *,
    allowed_user_id: int | None,
    state: Mapping[str, Any],
) -> TelegramIngress | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    sender = message.get("from")
    if not isinstance(chat, dict) or not isinstance(sender, dict):
        return None
    chat_type = str(chat.get("type") or "").strip().lower()
    if chat_type not in SUPPORTED_CHAT_TYPES:
        return None
    try:
        user_id = int(sender["id"])
        chat_id = int(chat["id"])
    except (KeyError, TypeError, ValueError):
        return None
    text = message.get("text")
    if not isinstance(text, str):
        text = message.get("caption")
    if not isinstance(text, str):
        text = ""

    authorized_sender = (
        allowed_user_id is not None and int(allowed_user_id) == user_id
    )
    authorized_chat = (
        authorized_sender and chat_id in configured_allowed_chat_ids(state)
    )
    return TelegramIngress(
        user_id=user_id,
        chat_id=chat_id,
        chat_type=chat_type,
        message=message,
        text=text.strip(),
        authorized_sender=authorized_sender,
        authorized_chat=authorized_chat,
    )


def enroll_allowed_chat(
    state: dict[str, Any],
    *,
    chat_id: int,
    authorized_user_id: int,
    sender_user_id: int,
) -> dict[str, Any]:
    if int(sender_user_id) != int(authorized_user_id):
        raise PermissionError("only the paired Telegram human may enroll a chat")
    allowed = configured_allowed_chat_ids(state)
    allowed.add(int(chat_id))
    state["allowed_chat_ids"] = sorted(allowed)
    return state
