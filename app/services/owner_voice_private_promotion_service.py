from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


VOICE_IDENTITY_ID="BR_OWNER_V1"
MODEL_ID="Qwen/Qwen3-TTS-12Hz-1.7B-Base"
MODEL_REVISION="fd4b254389122332181a7c3db7f27e918eec64e3"
PROVIDER_ID="qwen3-tts"
VOICE_PROMPT_REF="private://voice/BR_OWNER_V1/qwen-prompt/current"


class OwnerVoicePrivatePromotionError(RuntimeError):
    pass


def _sha256_bytes(value:bytes)->str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value:str)->str:
    return _sha256_bytes(str(value).encode("utf-8"))


def _valid_sha(value:Any)->bool:
    text=str(value or "").strip().lower()
    return len(text)==64 and all(ch in "0123456789abcdef" for ch in text)


def _canonical_json_bytes(value:Mapping[str,Any])->bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",",":"),
    ).encode("utf-8")


def _canonical_bytes(value:Mapping[str,Any])->bytes:
    return _canonical_json_bytes(value)+b"\n"


def _sha256_json(value:Mapping[str,Any])->str:
    return _sha256_bytes(_canonical_json_bytes(value))


def _outside_repository(path:Path,repository_root:Path)->None:
    try:
        path.resolve().relative_to(repository_root.resolve())
    except ValueError:
        return
    raise OwnerVoicePrivatePromotionError("PRIVATE_MATERIAL_MUST_BE_OUTSIDE_REPOSITORY")


def _atomic_write(path:Path,data:bytes,mode:int=0o600)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    temporary=path.with_suffix(path.suffix+".tmp")
    temporary.write_bytes(data)
    try:
        temporary.chmod(mode)
    except OSError:
        pass
    temporary.replace(path)
    try:
        path.chmod(mode)
    except OSError:
        pass


def _require_review_and_delivery(
    clone_delivery:Mapping[str,Any],
    human_review:Mapping[str,Any],
)->None:
    if (
        clone_delivery.get("schema_version")!="OwnerVoiceSingleCloneDelivery/v1"
        or clone_delivery.get("state")!="CONFIRMED"
        or clone_delivery.get("candidate_mode")!="SINGLE_CLONE"
        or clone_delivery.get("runtime_activation") is not False
    ):
        raise OwnerVoicePrivatePromotionError("CLONE_DELIVERY_NOT_PROMOTABLE")
    if (
        clone_delivery.get("clone_identity_gate")!="PASS"
        or clone_delivery.get("content_audio_prescreen")!="PASS"
    ):
        raise OwnerVoicePrivatePromotionError("AUTOMATIC_GATES_REQUIRED")

    if (
        human_review.get("schema")!="OwnerVoiceHumanReviewReceipt/v2"
        or human_review.get("voice_identity_id")!=VOICE_IDENTITY_ID
        or human_review.get("candidate_mode")!="SINGLE_CLONE"
        or human_review.get("status")!="APPROVED_PENDING_PROMOTION"
        or human_review.get("review_action")!="approve"
        or human_review.get("production_activation")!="BLOCKED_PENDING_PROMOTION"
        or human_review.get("authorized_human") is not True
        or human_review.get("production_authority") is not True
        or human_review.get("lineage_bound") is not True
        or human_review.get("automatic_gates_passed") is not True
    ):
        raise OwnerVoicePrivatePromotionError("HUMAN_APPROVAL_REQUIRED")

    token=str(clone_delivery.get("review_token") or "").strip().lower()
    if (
        not token
        or token!=str(human_review.get("review_token") or "").strip().lower()
    ):
        raise OwnerVoicePrivatePromotionError("REVIEW_BINDING_MISMATCH")

    lineage_keys=(
        "identity_anchor_telegram_input_id",
        "pronunciation_reference_telegram_input_ids",
        "vice_city_reference_telegram_input_id",
    )
    for key in lineage_keys:
        if clone_delivery.get(key)!=human_review.get(key):
            raise OwnerVoicePrivatePromotionError("REVIEW_BINDING_MISMATCH")


def _verified_reference(
    raw:Mapping[str,Any],
    *,
    expected_input_id:int,
    repository_root:Path,
)->dict[str,Any]:
    row=dict(raw)
    if int(row.get("telegram_input_id") or 0)!=int(expected_input_id):
        raise OwnerVoicePrivatePromotionError("PROMOTION_REFERENCE_ID_MISMATCH")
    source=Path(str(row.get("runtime_path") or "")).expanduser().resolve()
    _outside_repository(source,repository_root)
    if not source.is_file() or source.stat().st_size<=0:
        raise OwnerVoicePrivatePromotionError("PROMOTION_REFERENCE_MISSING")
    expected_sha=str(row.get("sha256") or "").strip().lower()
    if not _valid_sha(expected_sha):
        raise OwnerVoicePrivatePromotionError("PROMOTION_REFERENCE_HASH_INVALID")
    actual_sha=_sha256_bytes(source.read_bytes())
    if actual_sha!=expected_sha:
        raise OwnerVoicePrivatePromotionError("PROMOTION_REFERENCE_HASH_MISMATCH")
    ref_text=str(row.get("ref_text") or "").strip()
    if not ref_text:
        raise OwnerVoicePrivatePromotionError("PROMOTION_REFERENCE_TRANSCRIPT_REQUIRED")
    return {
        "telegram_input_id":int(expected_input_id),
        "source_path":source,
        "sha256":actual_sha,
        "ref_text":ref_text,
        "ref_text_sha256":_sha256_text(ref_text),
    }


def _copy_private_asset(
    row:Mapping[str,Any],
    *,
    private_root:Path,
)->dict[str,Any]:
    source=Path(str(row["source_path"])).resolve()
    suffix=source.suffix.lower()
    if suffix not in {".wav",".flac",".ogg",".mp3",".m4a",".opus"}:
        suffix=".audio"
    relative=Path("assets")/(
        f"{int(row['telegram_input_id']):06d}-"
        f"{str(row['sha256'])[:20]}{suffix}"
    )
    target=(private_root/relative).resolve()
    try:
        target.relative_to(private_root)
    except ValueError as exc:
        raise OwnerVoicePrivatePromotionError("PRIVATE_PROMOTION_PATH_ESCAPE") from exc
    data=source.read_bytes()
    if _sha256_bytes(data)!=str(row["sha256"]):
        raise OwnerVoicePrivatePromotionError("PROMOTION_REFERENCE_HASH_MISMATCH")
    if target.is_file():
        if _sha256_bytes(target.read_bytes())!=str(row["sha256"]):
            raise OwnerVoicePrivatePromotionError("PRIVATE_PROMOTION_ASSET_CONFLICT")
    else:
        _atomic_write(target,data,0o600)
    return {
        "audio_path":relative.as_posix(),
        "audio_sha256":str(row["sha256"]),
        "ref_text":str(row["ref_text"]),
    }


def promote_approved_owner_voice(
    *,
    clone_delivery:Mapping[str,Any],
    human_review:Mapping[str,Any],
    references_by_input_id:Mapping[int,Mapping[str,Any]],
    private_store_root:str|Path,
    repository_root:str|Path,
)->dict[str,Any]:
    _require_review_and_delivery(clone_delivery,human_review)

    repository=Path(repository_root).expanduser().resolve()
    private_root=Path(private_store_root).expanduser().resolve()
    _outside_repository(private_root,repository)
    private_root.mkdir(parents=True,exist_ok=True)
    try:
        private_root.chmod(0o700)
    except OSError:
        pass

    anchor_id=int(human_review["identity_anchor_telegram_input_id"])
    pronunciation_ids=[
        int(value)
        for value in human_review["pronunciation_reference_telegram_input_ids"]
    ]
    vice_id=int(human_review["vice_city_reference_telegram_input_id"])
    if (
        anchor_id<=0
        or not pronunciation_ids
        or len(pronunciation_ids)>2
        or vice_id not in pronunciation_ids
    ):
        raise OwnerVoicePrivatePromotionError("PROMOTION_LINEAGE_INVALID")

    required_ids={anchor_id,*pronunciation_ids}
    verified={}
    for input_id in sorted(required_ids):
        raw=references_by_input_id.get(input_id)
        if not isinstance(raw,Mapping):
            raise OwnerVoicePrivatePromotionError("PROMOTION_REFERENCE_MISSING")
        verified[input_id]=_verified_reference(
            raw,
            expected_input_id=input_id,
            repository_root=repository,
        )

    anchor_asset=_copy_private_asset(verified[anchor_id],private_root=private_root)
    vice_asset=_copy_private_asset(verified[vice_id],private_root=private_root)
    generic_id=next(
        (value for value in pronunciation_ids if value!=vice_id),
        vice_id,
    )
    english_asset=_copy_private_asset(
        verified[generic_id],
        private_root=private_root,
    )

    package={
        "schema":"OwnerVoiceQwenPromptPackage/v1",
        "voice_identity_id":VOICE_IDENTITY_ID,
        "model_id":MODEL_ID,
        "model_revision":MODEL_REVISION,
        "anchor":anchor_asset,
        "pronunciation_references":{
            "__english__":english_asset,
            "Vice City":vice_asset,
        },
    }
    package_path=private_root/f"{VOICE_IDENTITY_ID}.prompt.json"
    package_bytes=_canonical_bytes(package)
    _atomic_write(package_path,package_bytes,0o600)
    prompt_sha=_sha256_bytes(package_path.read_bytes())

    ordered_refs=[verified[input_id] for input_id in sorted(required_ids)]
    reviewed_at=float(human_review.get("recorded_at_epoch") or 0.0)
    timestamp=(
        datetime.fromtimestamp(reviewed_at,tz=timezone.utc)
        if reviewed_at>0
        else datetime.now(timezone.utc)
    ).isoformat().replace("+00:00","Z")
    profile={
        "schema":"VoiceIdentityProfile/v1",
        "voice_identity_id":VOICE_IDENTITY_ID,
        "owner_class":"OWNER",
        "language":"pt-BR",
        "accent_locale":"pt-BR",
        "reference_source":"TELEGRAM",
        "voice_selection_mode":"TELEGRAM_REFERENCE_CLONE",
        "preset_voice_used":False,
        "generic_voice_fallback":False,
        "source_audio_refs":[
            f"private://voice/{VOICE_IDENTITY_ID}/references/{row['sha256']}"
            for row in ordered_refs
        ],
        "source_audio_sha256s":[row["sha256"] for row in ordered_refs],
        "source_transcript_sha256s":[
            row["ref_text_sha256"] for row in ordered_refs
        ],
        "consent_status":"APPROVED",
        "consent_timestamp":timestamp,
        "clone_provider":PROVIDER_ID,
        "clone_model":MODEL_ID,
        "clone_model_revision":MODEL_REVISION,
        "voice_prompt_ref":VOICE_PROMPT_REF,
        "voice_prompt_sha256":prompt_sha,
        "quality_status":"READY",
        "review_token":str(human_review["review_token"]),
        "approved_clone_id":str(clone_delivery["clone_id"]),
        "created_at":timestamp,
        "updated_at":timestamp,
    }
    profile_path=private_root/f"{VOICE_IDENTITY_ID}.json"
    profile_bytes=_canonical_bytes(profile)
    _atomic_write(profile_path,profile_bytes,0o600)
    profile_sha=_sha256_json(profile)

    receipt={
        "schema":"OwnerVoicePrivatePromotionReceipt/v1",
        "status":"PROMOTED_PRIVATE_PENDING_PUBLIC_ACTIVATION",
        "voice_identity_id":VOICE_IDENTITY_ID,
        "clone_id":str(clone_delivery["clone_id"]),
        "review_token":str(human_review["review_token"]),
        "provider":PROVIDER_ID,
        "model":MODEL_ID,
        "model_revision":MODEL_REVISION,
        "voice_prompt_sha256":prompt_sha,
        "profile_sha256":profile_sha,
        "reference_set_sha256":_sha256_json({
            "source_audio_sha256s":profile["source_audio_sha256s"],
            "source_transcript_sha256s":profile["source_transcript_sha256s"],
        }),
        "automatic_gates_passed":True,
        "human_review_status":"APPROVED_PENDING_PROMOTION",
        "runtime_activation":False,
        "next_gate":"PUBLIC_RUNTIME_ACTIVATION_TRANSACTION",
    }
    receipt_path=private_root/f"{VOICE_IDENTITY_ID}.promotion.json"
    _atomic_write(receipt_path,_canonical_bytes(receipt),0o600)
    return receipt
