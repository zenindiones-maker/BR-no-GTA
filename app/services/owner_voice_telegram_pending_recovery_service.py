from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

from app.services.owner_voice_telegram_handoff_service import (
    build_owner_voice_reference_index,
)


class OwnerVoicePendingTelegramRecoveryError(RuntimeError):
    pass


def recover_pending_owner_voice_references(
    *,
    telegram_bot_token: str,
    reference_index: Mapping[str, Any],
    after_message_id: int,
    api_call: Callable[[str, str, dict[str, Any]], Any] | None = None,
    verified_ingress_records: Iterable[Mapping[str, Any]] | None = None,
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

    # The owning gateway/webhook MUST ingest and remotely verify records first.
    # Recovery does not own the Telegram update queue: no polling, webhook
    # mutation, offset advancement or external side effect is permitted.
    if api_call is not None:
        raise OwnerVoicePendingTelegramRecoveryError(
            "DIRECT_GETUPDATES_RECOVERY_FORBIDDEN"
        )
    if verified_ingress_records is None:
        raise OwnerVoicePendingTelegramRecoveryError(
            "VERIFIED_INGRESS_REQUIRED"
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
    for row in verified_ingress_records:
        if not isinstance(row, Mapping) or row.get("remote_verified") is not True:
            continue
        try:
            user_id=int(row.get("telegram_user_id") or 0)
            chat_id=int(row.get("telegram_chat_id") or 0)
            message_id=int(row.get("telegram_message_id") or 0)
            update_id=int(row.get("telegram_update_id") or 0)
            input_id=int(row.get("id") or 0)
        except (ValueError, TypeError):
            continue
        kind=str(row.get("input_kind") or "").lower().strip()
        file_id=str(row.get("telegram_file_id") or "").strip()
        unique_id=str(row.get("telegram_file_unique_id") or "").strip()
        if user_id!=owner_user_id or chat_id not in chat_ids:
            continue
        if message_id<=cutoff or not update_id or not input_id:
            continue
        if kind not in {"voice", "audio"} or not file_id or not unique_id:
            continue
        identity=(chat_id,message_id,unique_id)
        if identity in known:
            continue
        known.add(identity)
        recovered_records.append({
            "id":input_id,
            "telegram_user_id":user_id,
            "telegram_chat_id":chat_id,
            "telegram_message_id":message_id,
            "telegram_update_id":update_id,
            "input_kind":kind,
            "telegram_file_id":file_id,
            "telegram_file_unique_id":unique_id,
            "duration_seconds":row.get("duration_seconds"),
            "mime_type":str(row.get("mime_type") or "").strip() or None,
            "file_size":row.get("file_size"),
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
