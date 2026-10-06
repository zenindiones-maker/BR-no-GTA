from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

REFERENCE_SELECTION_SCHEMA="OwnerVoiceReferenceSelectionReceipt/v1"
PERFORMANCE_SCHEMA="OwnerVoicePerformanceReceipt/v1"
VOICE_IDENTITY_ID="BR_OWNER_V1"
REFERENCE_SOURCE="TELEGRAM"
REFERENCE_SELECTION_MISSION_ID="owner-voice-reference-selection-v1"


def _canon(value: Any) -> bytes:
    return json.dumps(
        value,ensure_ascii=True,sort_keys=True,separators=(",",":"),default=str
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canon(value)).hexdigest()


def build_selection_policy_hash() -> str:
    return _sha({
        "contract":"QUALITY_FIRST_DETERMINISTIC",
        "version":2,
        "ptbr_probability_min":0.90,
        "snr_db_min":15.0,
        "clipping_ratio_max":0.01,
        "speech_ratio_min":0.55,
        "preferred_reference_seconds":[6.0,10.0],
        "preferred_target_seconds":8.0,
        "ranking":[
            "-quality_score","duration_bucket","duration_distance",
            "-snr_db","sha256","telegram_input_id",
        ],
        "fallback":"EXACT_BRANCH_AND_BOUND",
    })


def build_stt_contract_hash(model_id: str) -> str:
    return _sha({
        "faster_whisper_version":"1.2.0",
        "pyav_version":"18.0.0",
        "model_id":str(model_id),
        "device":"cpu",
        "compute_type":"int8",
        "reference_beam_size":5,
        "reference_vad_filter":True,
        "reference_word_timestamps":True,
        "reference_condition_on_previous_text":True,
    })


def _receipt_content(receipt: Mapping[str,Any]) -> dict[str,Any]:
    keys=(
        "schema_version","reference_set_digest","selection_policy_hash",
        "stt_contract_hash","selected_telegram_input_id","selected_audio_sha256",
        "quality_score","ptbr_probability","transcription_confidence",
        "reference_source","voice_identity_id",
    )
    return {key:receipt.get(key) for key in keys}


def build_reference_selection_receipt(
    *,
    reference_set_digest: str,
    selection_policy_hash: str,
    stt_contract_hash: str,
    selected_telegram_input_id: int,
    selected_audio_sha256: str,
    quality_score: float,
    ptbr_probability: float,
    transcription_confidence: float,
) -> dict[str,Any]:
    payload={
        "schema_version":REFERENCE_SELECTION_SCHEMA,
        "reference_set_digest":str(reference_set_digest).lower(),
        "selection_policy_hash":str(selection_policy_hash).lower(),
        "stt_contract_hash":str(stt_contract_hash).lower(),
        "selected_telegram_input_id":int(selected_telegram_input_id),
        "selected_audio_sha256":str(selected_audio_sha256).lower(),
        "quality_score":float(quality_score),
        "ptbr_probability":float(ptbr_probability),
        "transcription_confidence":float(transcription_confidence),
        "reference_source":REFERENCE_SOURCE,
        "voice_identity_id":VOICE_IDENTITY_ID,
    }
    if (
        int(payload["selected_telegram_input_id"])<=0
        or any(len(str(payload[key]))!=64 for key in (
            "reference_set_digest","selection_policy_hash",
            "stt_contract_hash","selected_audio_sha256",
        ))
    ):
        raise ValueError("REFERENCE_SELECTION_RECEIPT_INVALID")
    payload["content_sha256"]=_sha(payload)
    return payload


def validate_reference_selection_receipt(
    receipt: Mapping[str,Any],
    *,
    reference_set_digest: str,
    selection_policy_hash: str,
    stt_contract_hash: str,
) -> bool:
    row=dict(receipt or {})
    if (
        row.get("schema_version")!=REFERENCE_SELECTION_SCHEMA
        or row.get("voice_identity_id")!=VOICE_IDENTITY_ID
        or row.get("reference_source")!=REFERENCE_SOURCE
        or str(row.get("reference_set_digest") or "").lower()!=str(reference_set_digest).lower()
        or str(row.get("selection_policy_hash") or "").lower()!=str(selection_policy_hash).lower()
        or str(row.get("stt_contract_hash") or "").lower()!=str(stt_contract_hash).lower()
        or int(row.get("selected_telegram_input_id") or 0)<=0
    ):
        return False
    digest=str(row.get("selected_audio_sha256") or "").lower()
    if len(digest)!=64 or any(ch not in "0123456789abcdef" for ch in digest):
        return False
    expected=_sha(_receipt_content(row))
    return str(row.get("content_sha256") or "").lower()==expected


class GitBackedReferenceSelectionReceiptLedger:
    def __init__(self,store)->None:
        self.store=store
        self.mission_id=REFERENCE_SELECTION_MISSION_ID

    def load(self)->dict[str,Any]|None:
        snap=self.store.snapshot(self.mission_id)
        head=snap.mission_head
        if not isinstance(head,dict):
            return None
        return dict(head)

    def persist(self,receipt: Mapping[str,Any])->dict[str,Any]:
        snap=self.store.snapshot(self.mission_id)
        current=dict(snap.mission_head or {})
        prior=None if not current else int(current.get("state_version",-1))
        next_version=0 if prior is None else prior+1
        head={**dict(receipt),"mission_id":self.mission_id,"state_version":next_version}
        self.store.transact(
            mission_id=self.mission_id,
            expected_head_sha=snap.head_sha,
            expected_state_version=prior,
            mission_head=head,
            immutable_objects={
                f"missions/{self.mission_id}/events/v{next_version:06d}.json":{
                    "event":"REFERENCE_SELECTION_RECEIPT",
                    **dict(receipt),
                }
            },
        )
        loaded=self.load()
        if not isinstance(loaded,dict):
            raise RuntimeError("REFERENCE_SELECTION_RECEIPT_READBACK_FAILED")
        return loaded


def build_performance_receipt(values: Mapping[str,Any])->dict[str,Any]:
    allowed=(
        "SECRET_PREFLIGHT_SECONDS","STT_RUNTIME_SETUP_SECONDS","REFERENCE_QA_SECONDS",
        "CHATTERBOX_RUNTIME_SETUP_SECONDS","MODEL_ASSET_RESTORE_SECONDS",
        "REFERENCE_CONDITIONALS_SECONDS","CANDIDATE_A_GENERATION_SECONDS",
        "CANDIDATE_B_GENERATION_SECONDS","CANDIDATE_C_GENERATION_SECONDS",
        "MACHINE_PRESCREEN_SECONDS","TELEGRAM_DELIVERY_SECONDS","TOTAL_AUDITION_SECONDS",
        "PUBLIC_MODEL_CACHE_HIT","REFERENCE_SELECTION_CACHE_HIT",
        "STT_NETWORK_DOWNLOAD_COUNT","CHATTERBOX_NETWORK_DOWNLOAD_COUNT",
        "CHATTERBOX_GENERATE_CALL_COUNT","REFERENCE_ASR_COUNT",
        "MARGINAL_ASR_ESCALATIONS","OWNER_AUDITION_TEXT_CHARS",
        "CONDITIONALS_PREPARE_COUNT","CONDITIONALS_REUSED","STT_MODEL_PATH_REUSED",
    )
    payload={
        "schema_version":PERFORMANCE_SCHEMA,
        "voice_identity_id":VOICE_IDENTITY_ID,
        "reference_source":"TELEGRAM_HUMAN_OWNER",
    }
    for key in allowed:
        if key in values and values[key] not in (None,""):
            payload[key]=values[key]
    total=float(payload.get("TOTAL_AUDITION_SECONDS") or 0.0)
    public_hit=str(payload.get("PUBLIC_MODEL_CACHE_HIT") or "").lower()=="true"
    selection_hit=str(payload.get("REFERENCE_SELECTION_CACHE_HIT") or "").lower()=="true"
    payload["WARM_RUN_TARGET_MET"]=(total>0 and total<=900.0) if (public_hit and selection_hit) else None
    payload["COLD_RUN_TARGET_MET"]=(total>0 and total<=1200.0) if not (public_hit and selection_hit) else None
    payload["content_sha256"]=_sha(payload)
    return payload
