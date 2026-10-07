from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from app.services.owner_voice_telegram_handoff_service import (
    build_owner_voice_reference_index,
)


class OwnerVoicePendingTelegramRecoveryError(RuntimeError):
    pass


def _message_media(message: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]] | None:
    voice=message.get("voice")
    if isinstance(voice, Mapping):
        return "voice", voice
    audio=message.get("audio")
    if isinstance(audio, Mapping):
        return "audio", audio
    return None


def recover_pending_owner_voice_references(
    *,
    telegram_bot_token: str,
    reference_index: Mapping[str, Any],
    after_message_id: int,
    api_call: Callable[[str, str, dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    token=str(telegram_bot_token or "").strip()
    if not token:
        raise OwnerVoicePendingTelegramRecoveryError(
            "TELEGRAM_BOT_TOKEN_NOT_MATERIALIZED"
        )
    cutoff=int(after_message_id)
    if cutoff < 0:
        raise OwnerVoicePendingTelegramRecoveryError(
            "OWNER_PRONUNCIATION_REFERENCE_BOUNDARY_INVALID"
        )

    existing=list(reference_index.get("references") or [])
    owner_ids={
        int(row["telegram_user_id"])
        for row in existing
        if isinstance(row, Mapping) and row.get("telegram_user_id") is not None
    }
    chat_ids={
        int(row["telegram_chat_id"])
        for row in existing
        if isinstance(row, Mapping) and row.get("telegram_chat_id") is not None
    }
    if len(owner_ids)!=1 or not chat_ids:
        raise OwnerVoicePendingTelegramRecoveryError(
            "OWNER_PENDING_RECOVERY_AUTHORITY_AMBIGUOUS"
        )
    owner_user_id=next(iter(owner_ids))

    if api_call is None:
        from app.services.telegram_brand_asset_materializer import (
            _telegram_api_call as telegram_api_call,
        )
        api_call=telegram_api_call

    updates=api_call(
        token,
        "getUpdates",
        {
            "limit":100,
            "timeout":0,
            "allowed_updates":json.dumps(["message"],separators=(",",":")),
        },
    )
    if not isinstance(updates,list):
        raise OwnerVoicePendingTelegramRecoveryError(
            "OWNER_PENDING_RECOVERY_RESPONSE_INVALID"
        )

    known={
        (
            int(row.get("telegram_chat_id") or 0),
            int(row.get("telegram_message_id") or 0),
            str(row.get("telegram_file_unique_id") or ""),
        )
        for row in existing
        if isinstance(row, Mapping)
    }
    recovered_records=[]
    for update in updates:
        if not isinstance(update,Mapping):
            continue
        message=update.get("message")
        if not isinstance(message,Mapping):
            continue
        sender=message.get("from")
        chat=message.get("chat")
        if not isinstance(sender,Mapping) or not isinstance(chat,Mapping):
            continue
        telegram_user_id=int(sender.get("id") or 0)
        telegram_chat_id=int(chat.get("id") or 0)
        message_id=int(message.get("message_id") or 0)
        update_id=int(update.get("update_id") or 0)
        if telegram_user_id!=owner_user_id or telegram_chat_id not in chat_ids:
            continue
        if message_id<=cutoff or update_id<=0:
            continue
        selected=_message_media(message)
        if selected is None:
            continue
        media_kind,media=selected
        file_id=str(media.get("file_id") or "").strip()
        unique_id=str(media.get("file_unique_id") or "").strip()
        if not file_id or not unique_id:
            continue
        identity=(telegram_chat_id,message_id,unique_id)
        if identity in known:
            continue
        known.add(identity)
        recovered_records.append({
            "id":-update_id,
            "telegram_user_id":telegram_user_id,
            "telegram_chat_id":telegram_chat_id,
            "telegram_message_id":message_id,
            "telegram_update_id":update_id,
            "input_kind":media_kind,
            "telegram_file_id":file_id,
            "telegram_file_unique_id":unique_id,
            "duration_seconds":media.get("duration"),
            "mime_type":str(media.get("mime_type") or "").strip() or None,
            "file_size":media.get("file_size"),
            "remote_verified":True,
        })

    existing_records=[
        {
            "id":int(row["telegram_input_id"]),
            "telegram_user_id":int(row["telegram_user_id"]),
            "telegram_chat_id":int(row["telegram_chat_id"]),
            "telegram_message_id":int(row["telegram_message_id"]),
            "telegram_update_id":int(row["telegram_update_id"]),
            "input_kind":str(row["input_kind"]),
            "telegram_file_id":str(row["telegram_file_id"]),
            "telegram_file_unique_id":str(row["telegram_file_unique_id"]),
            "duration_seconds":row.get("duration_seconds"),
            "mime_type":row.get("mime_type"),
            "file_size":row.get("file_size"),
            "remote_verified":True,
        }
        for row in existing
    ]
    merged_index=build_owner_voice_reference_index(
        records=[*existing_records,*recovered_records],
        owner_user_id=owner_user_id,
        allowed_chat_ids=set(chat_ids),
    )
    return {
        "schema":"OwnerVoicePendingTelegramRecovery/v1",
        "telegram_user_id":owner_user_id,
        "telegram_chat_id":sorted(chat_ids),
        "after_message_id":cutoff,
        "recovered_reference_count":len(recovered_records),
        "non_acknowledging":True,
        "merged_index":merged_index,
    }
