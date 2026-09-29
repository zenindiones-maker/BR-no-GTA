from __future__ import annotations

from typing import Any

from app.database.telegram_egress_outbox_repository import (
    get_telegram_egress_operation,
    update_telegram_egress_operation,
)


def deliver_telegram_egress_operation(api, operation: dict[str, Any]) -> dict[str, Any]:
    operation_id = str(operation.get("operation_id") or "")
    current = get_telegram_egress_operation(operation_id) or dict(operation)
    state = str(current.get("state") or "").upper()
    if state in {"SENT", "UNKNOWN_REMOTE_STATE", "FAILED_PERMANENT"}:
        return current
    if state == "SENDING":
        # A previous process may have crossed the external POST boundary before
        # crashing. Without a Telegram idempotency key or receipt, resend is unsafe.
        return update_telegram_egress_operation(
            operation_id,
            state="UNKNOWN_REMOTE_STATE",
            last_error="process restarted with ambiguous SENDING egress state",
        )

    current = update_telegram_egress_operation(
        operation_id,
        state="SENDING",
        increment_attempt=True,
    )
    try:
        edit_message_id = current.get("edit_message_id")
        if edit_message_id is not None:
            api.edit(
                int(current["chat_id"]),
                int(edit_message_id),
                str(current["payload_text"]),
            )
            return update_telegram_egress_operation(
                operation_id,
                state="SENT",
                telegram_message_id=int(edit_message_id),
            )

        message_id = api.send(
            int(current["chat_id"]),
            str(current["payload_text"]),
            reply_to_message_id=current.get("reply_to_message_id"),
        )
        if not isinstance(message_id, int):
            return update_telegram_egress_operation(
                operation_id,
                state="UNKNOWN_REMOTE_STATE",
                last_error="Telegram send returned no message receipt",
            )
        return update_telegram_egress_operation(
            operation_id,
            state="SENT",
            telegram_message_id=message_id,
        )
    except Exception as exc:
        # Bot API has no application-provided idempotency key. Once the POST
        # boundary may have been crossed, resend is unsafe without reconciliation.
        return update_telegram_egress_operation(
            operation_id,
            state="UNKNOWN_REMOTE_STATE",
            last_error=f"{type(exc).__name__}:{str(exc)[:1000]}",
        )
