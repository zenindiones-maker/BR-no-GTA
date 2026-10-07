from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.owner_voice_private_promotion_service import (
    OwnerVoicePrivatePromotionError,
    promote_approved_owner_voice,
)


VOICE_IDENTITY_ID="BR_OWNER_V1"
PROVIDER_ID="qwen3-tts"
MODEL_ID="Qwen/Qwen3-TTS-12Hz-1.7B-Base"
MODEL_REVISION="fd4b254389122332181a7c3db7f27e918eec64e3"


class OwnerVoiceQwenPromotionError(RuntimeError):
    pass


def _canonical_bytes(value:Mapping[str,Any])->bytes:
    return (
        json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",",":"),
        )
        +"\n"
    ).encode("utf-8")


def _atomic_private_write(path:Path,data:bytes)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_bytes(data)
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _lineage_tuple(row:Mapping[str,Any])->tuple[int,tuple[int,...],int|None]:
    try:
        anchor=int(row.get("identity_anchor_telegram_input_id") or 0)
        pronunciation=tuple(
            int(value)
            for value in (row.get("pronunciation_reference_telegram_input_ids") or [])
        )
        raw_vice=row.get("vice_city_reference_telegram_input_id")
        vice=int(raw_vice) if raw_vice is not None else None
    except (TypeError,ValueError) as exc:
        raise OwnerVoiceQwenPromotionError("LINEAGE_MISMATCH") from exc
    return anchor,pronunciation,vice


def _validate_activation_boundary(
    review_receipt:Mapping[str,Any],
    delivery_state:Mapping[str,Any],
)->None:
    if (
        review_receipt.get("schema")!="OwnerVoiceHumanReviewReceipt/v2"
        or review_receipt.get("voice_identity_id")!=VOICE_IDENTITY_ID
        or review_receipt.get("candidate_mode")!="SINGLE_CLONE"
        or review_receipt.get("status")!="APPROVED_PENDING_PROMOTION"
        or review_receipt.get("review_action")!="approve"
        or review_receipt.get("authorized_human") is not True
        or review_receipt.get("production_authority") is not True
        or review_receipt.get("lineage_bound") is not True
    ):
        raise OwnerVoiceQwenPromotionError("HUMAN_APPROVAL_REQUIRED")
    if (
        delivery_state.get("schema_version")!="OwnerVoiceSingleCloneDelivery/v1"
        or delivery_state.get("state")!="CONFIRMED"
        or delivery_state.get("candidate_mode")!="SINGLE_CLONE"
        or delivery_state.get("runtime_activation") is not False
    ):
        raise OwnerVoiceQwenPromotionError("DELIVERY_STATE_NOT_PROMOTABLE")
    if (
        review_receipt.get("automatic_gates_passed") is not True
        or delivery_state.get("clone_identity_gate")!="PASS"
        or delivery_state.get("content_audio_prescreen")!="PASS"
    ):
        raise OwnerVoiceQwenPromotionError("AUTOMATIC_GATES_REQUIRED")
    if str(review_receipt.get("review_token") or "")!=str(
        delivery_state.get("review_token") or ""
    ):
        raise OwnerVoiceQwenPromotionError("LINEAGE_MISMATCH")
    if _lineage_tuple(review_receipt)!=_lineage_tuple(delivery_state):
        raise OwnerVoiceQwenPromotionError("LINEAGE_MISMATCH")
    confirmed=dict(delivery_state.get("confirmed_message_ids") or {})
    control_id=int(confirmed.get("control") or 0)
    if (
        control_id<=0
        or int(review_receipt.get("telegram_message_id") or 0)!=control_id
    ):
        raise OwnerVoiceQwenPromotionError("LINEAGE_MISMATCH")
    delivery_chat=int(delivery_state.get("telegram_chat_id") or 0)
    review_chat=int(review_receipt.get("telegram_chat_id") or 0)
    if delivery_chat==0 or delivery_chat!=review_chat:
        raise OwnerVoiceQwenPromotionError("LINEAGE_MISMATCH")


def promote_approved_single_clone(
    *,
    review_receipt:Mapping[str,Any],
    delivery_state:Mapping[str,Any],
    materialized_references:Sequence[Mapping[str,Any]],
    reference_transcripts:Mapping[int,str],
    private_store_root:str|Path,
    repository_root:str|Path,
    promoted_at:str|None=None,
)->dict[str,Any]:
    _validate_activation_boundary(review_receipt,delivery_state)

    by_id={}
    for raw in materialized_references:
        row=dict(raw)
        input_id=int(row.get("telegram_input_id") or 0)
        if input_id<=0:
            raise OwnerVoiceQwenPromotionError("PROMOTION_REFERENCE_INVALID")
        transcript=str(
            reference_transcripts.get(input_id)
            or reference_transcripts.get(str(input_id))  # type: ignore[arg-type]
            or ""
        ).strip()
        if not transcript:
            raise OwnerVoiceQwenPromotionError("PROMOTION_TRANSCRIPT_REQUIRED")
        row["ref_text"]=transcript
        by_id[input_id]=row

    try:
        staged=promote_approved_owner_voice(
            clone_delivery=delivery_state,
            human_review=review_receipt,
            references_by_input_id=by_id,
            private_store_root=private_store_root,
            repository_root=repository_root,
        )
    except OwnerVoicePrivatePromotionError as exc:
        code=str(exc)
        if code=="REVIEW_BINDING_MISMATCH":
            code="LINEAGE_MISMATCH"
        raise OwnerVoiceQwenPromotionError(code) from exc

    root=Path(private_store_root).expanduser().resolve()
    activated_at=str(promoted_at or "").strip()
    if not activated_at:
        activated_at=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    activation={
        "schema":"OwnerVoiceRuntimeActivation/v1",
        "status":"READY",
        "voice_identity_id":VOICE_IDENTITY_ID,
        "provider":PROVIDER_ID,
        "model":MODEL_ID,
        "model_revision":MODEL_REVISION,
        "clone_id":str(delivery_state["clone_id"]),
        "review_token":str(review_receipt["review_token"]),
        "automatic_gates_passed":True,
        "human_review_status":"APPROVED_PENDING_PROMOTION",
        "profile_sha256":str(staged["profile_sha256"]),
        "voice_prompt_sha256":str(staged["voice_prompt_sha256"]),
        "reference_set_sha256":str(staged["reference_set_sha256"]),
        "runtime_activation":True,
        "activated_at":activated_at,
        "activation_authority":"AUTHORIZED_HUMAN_REVIEW_PLUS_AUTOMATIC_GATES",
    }
    _atomic_private_write(
        root/f"{VOICE_IDENTITY_ID}.runtime.json",
        _canonical_bytes(activation),
    )
    return {
        **staged,
        **activation,
        "schema":"OwnerVoiceQwenPromotionReceipt/v1",
        "status":"READY",
    }
