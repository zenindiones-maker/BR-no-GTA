from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

CURRENT_STEP="initialize"
_EXPECTED_BY_STEP={
    "input_contract":"explicit manifest_path and pack_id from generator outputs",
    "audition_handoff":"manifest digest, pack id, workspace binding, and A/B/C hashes valid",
    "reference_provenance":"selected real Telegram owner reference bound to manifest",
    "machine_prescreen":"three readable non-empty pt-BR candidates pass deterministic machine QA",
    "telegram_delivery":"durable SENDING-before-side-effect Telegram delivery reaches CONFIRMED",
}
_NEXT_BY_STEP={
    "input_contract":"repair explicit workflow handoff; do not reconstruct legacy paths",
    "audition_handoff":"repair or regenerate the handoff; do not send Telegram",
    "reference_provenance":"repair Telegram owner-reference provenance; do not generate fallback voice",
    "machine_prescreen":"repair generation or QA cause; do not send Telegram",
    "telegram_delivery":"inspect sanitized Telegram/ledger failure; reconcile ambiguous sends before retry",
}

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from app.services.owner_voice_audio_quality_service import pcm16_quality_metrics
from app.services.owner_voice_audition_handoff_service import consume_audition_handoff
from app.services.owner_voice_audition_ledger_store import store_from_environment
from app.services.owner_voice_audition_delivery_service import (
    GitBackedAuditionDeliveryLedger,
    SIDE_EFFECT_RECONCILIATION_REQUIRED,
    deliver_owner_voice_audition_durable,
)
from app.services.owner_voice_human_audition_pack_service import (
    build_pack_intro_message,
    build_pack_review_markup,
    evaluate_short_candidate,
)
from scripts.owner_voice_chatterbox_ptbr_audition import (
    MODEL_ID,
    MODEL_REVISION,
    _load_reference_index_from_environment,
)


def _normalize_for_qa(source: Path,target: Path) -> Path:
    target.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run([
        "ffmpeg","-y","-v","error","-i",str(source),
        "-vn","-ac","1","-ar","16000","-c:a","pcm_s16le",str(target),
    ],check=True,capture_output=True)
    if not target.is_file() or target.stat().st_size<=0:
        raise RuntimeError("OWNER_AUDITION_QA_NORMALIZATION_FAILED")
    return target


def _transcription_confidence(segments) -> float:
    import math
    values=[]
    for segment in segments:
        for word in getattr(segment,"words",None) or ():
            p=getattr(word,"probability",None)
            if isinstance(p,(int,float)) and 0<=float(p)<=1:
                values.append(float(p))
        avg=getattr(segment,"avg_logprob",None)
        if not values and isinstance(avg,(int,float)) and math.isfinite(float(avg)):
            values.append(max(0.0,min(1.0,math.exp(float(avg)))))
    return (sum(values)/len(values)) if values else 0.0



def _vad_speech_occupancy(segments, duration_seconds: float) -> float:
    duration=max(0.0,float(duration_seconds or 0.0))
    if duration<=0.0:
        return 0.0
    intervals=[]
    for segment in segments:
        start=max(0.0,min(duration,float(getattr(segment,"start",0.0) or 0.0)))
        end=max(start,min(duration,float(getattr(segment,"end",start) or start)))
        if end>start:
            intervals.append((start,end))
    if not intervals:
        return 0.0
    intervals.sort()
    merged=[]
    for start,end in intervals:
        if not merged or start>merged[-1][1]:
            merged.append([start,end])
        else:
            merged[-1][1]=max(merged[-1][1],end)
    speech=sum(end-start for start,end in merged)
    return max(0.0,min(1.0,speech/duration))


def _sanitized_machine_qa(row: Mapping[str,Any]) -> dict[str,Any]:
    return {
        "schema_version":"MachineAuditionCandidateQA/v1",
        "candidate_id":str(row.get("candidate_id") or ""),
        "audio_sha256":str(row.get("audio_sha256") or ""),
        "eligible":bool(row.get("eligible") is True),
        "issues":[str(x) for x in (row.get("issues") or [])],
        "detected_language":str(row.get("detected_language") or ""),
        "language_probability":float(row.get("language_probability") or 0.0),
        "word_error_rate":float(row.get("word_error_rate") or 0.0),
        "character_error_rate":float(row.get("character_error_rate") or 0.0),
        "duration_seconds":float(row.get("duration_seconds") or 0.0),
        "clipping_ratio":float(row.get("clipping_ratio") or 0.0),
        "speech_ratio":float(row.get("speech_ratio_for_gate") or 0.0),
        "amplitude_speech_ratio":float(row.get("amplitude_speech_ratio") or 0.0),
        "vad_speech_ratio":(
            None if row.get("vad_speech_ratio") is None
            else float(row.get("vad_speech_ratio") or 0.0)
        ),
        "speech_ratio_source":str(row.get("speech_ratio_source") or ""),
        "missing_word_estimate":int(row.get("missing_word_estimate") or 0),
        "inserted_word_estimate":int(row.get("inserted_word_estimate") or 0),
        "repetition_count":int(row.get("adjacent_repetition_count") or 0),
    }


def _emit_sanitized_candidate_qa(row: Mapping[str,Any]) -> None:
    label=str(row.get("candidate_id") or "").upper()
    issues=",".join(str(x) for x in (row.get("issues") or [])) or "NONE"
    def emit(name: str,value: Any) -> None:
        print(f"CANDIDATE_{label}_{name}={value}")
    emit("QA_ELIGIBLE","true" if row.get("eligible") is True else "false")
    emit("QA_ISSUES",issues)
    emit("LANGUAGE",row.get("detected_language") or "")
    emit("LANGUAGE_PROBABILITY",row.get("language_probability") or 0.0)
    emit("WER",row.get("word_error_rate") or 0.0)
    emit("CER",row.get("character_error_rate") or 0.0)
    emit("DURATION_SECONDS",row.get("duration_seconds") or 0.0)
    emit("CLIPPING_RATIO",row.get("clipping_ratio") or 0.0)
    emit("SPEECH_RATIO",row.get("speech_ratio_for_gate") or 0.0)
    emit("AMPLITUDE_SPEECH_RATIO",row.get("amplitude_speech_ratio") or 0.0)
    emit("VAD_SPEECH_RATIO","NONE" if row.get("vad_speech_ratio") is None else row.get("vad_speech_ratio"))
    emit("SPEECH_RATIO_SOURCE",row.get("speech_ratio_source") or "")
    emit("MISSING_WORD_ESTIMATE",row.get("missing_word_estimate") or 0)
    emit("INSERTED_WORD_ESTIMATE",row.get("inserted_word_estimate") or 0)
    emit("REPETITION_COUNT",row.get("adjacent_repetition_count") or 0)


def _write_machine_qa(path: Path, rows: list[Mapping[str,Any]]) -> list[dict[str,Any]]:
    sanitized=[_sanitized_machine_qa(row) for row in rows]
    payload={
        "schema_version":"MachineAuditionQASet/v1",
        "candidates":sanitized,
    }
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name("."+path.name+".tmp")
    tmp.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    os.replace(tmp,path)
    return sanitized


def _write_machine_prescreen_failure_receipt(
    path: Path,
    *,
    pack_id: str,
    sanitized_qa: list[Mapping[str,Any]],
) -> None:
    payload={
        "schema_version":"OwnerVoiceAuditionFailureReceipt/v1",
        "run_id":str(os.environ.get("GITHUB_RUN_ID") or ""),
        "pack_id":str(pack_id),
        "candidate_hashes":{
            str(row.get("candidate_id") or ""):str(row.get("audio_sha256") or "")
            for row in sanitized_qa
        },
        "candidate_qa":[dict(row) for row in sanitized_qa],
        "failure_step":"machine_prescreen",
        "failure_class":"RuntimeError:OWNER_AUDITION_MACHINE_PRESCREEN_FAILED",
        "side_effect_state":"NOT_STARTED",
    }
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name("."+path.name+".tmp")
    tmp.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    os.replace(tmp,path)

def _telegram_post(token: str,method: str,*,data: Mapping[str,Any],files=None) -> Any:
    import requests
    response=requests.post(
        f"https://api.telegram.org/bot{token}/{method}",
        data=dict(data),files=files,timeout=180,
    )
    try:
        payload=response.json()
    except Exception:
        payload={}
    if response.status_code!=200 or not isinstance(payload,dict) or payload.get("ok") is not True:
        error_code=payload.get("error_code") if isinstance(payload,dict) else None
        description=str(payload.get("description") or "unavailable") if isinstance(payload,dict) else "unavailable"
        description=" ".join(description.split())[:160]
        raise RuntimeError(
            f"TELEGRAM_METHOD={method}:HTTP_STATUS={response.status_code}:"
            f"TELEGRAM_ERROR_CODE={error_code}:DESCRIPTION={description}"
        )
    return payload.get("result")


class TelegramAuditionApi:
    def __init__(self,*,token: str,source_chat_id: int,review_markup: Mapping[str,Any]):
        self.token=token
        self.source_chat_id=int(source_chat_id)
        self.review_markup=dict(review_markup)

    def copy_reference(self,*,chat_id: int,source_message_id: int,protect_content: bool) -> int:
        result=_telegram_post(self.token,"copyMessage",data={
            "chat_id":str(chat_id),
            "from_chat_id":str(self.source_chat_id),
            "message_id":str(source_message_id),
            "caption":"🎤 REFERÊNCIA REAL DO HUMANO — comparação de identidade BR_OWNER_V1",
            "protect_content":"true" if protect_content else "false",
        })
        return int(result["message_id"])

    def send_media_group(self,*,chat_id: int,candidates: list[Mapping[str,Any]],protect_content: bool) -> list[int]:
        media=[]
        handles=[]
        files={}
        try:
            for row in candidates:
                label=str(row["candidate_id"])
                path=Path(str(row["runtime_path"])).resolve()
                handle=path.open("rb")
                handles.append(handle)
                attach=f"candidate_{label}"
                files[attach]=(f"BR_OWNER_V1_{label}.wav",handle,"audio/wav")
                media.append({
                    "type":"audio",
                    "media":f"attach://{attach}",
                    "caption":f"🎙️ CANDIDATO {label} — prova cega BR_OWNER_V1",
                })
            result=_telegram_post(self.token,"sendMediaGroup",data={
                "chat_id":str(chat_id),
                "media":json.dumps(media,ensure_ascii=False,separators=(",",":")),
                "protect_content":"true" if protect_content else "false",
            },files=files)
        finally:
            for handle in handles:
                handle.close()
        if not isinstance(result,list) or len(result)!=3:
            raise RuntimeError("TELEGRAM_SEND_MEDIA_GROUP_RECEIPT_INVALID")
        return [int(row["message_id"]) for row in result]

    def send_control(self,*,chat_id: int,protect_content: bool) -> int:
        result=_telegram_post(self.token,"sendMessage",data={
            "chat_id":str(chat_id),
            "text":build_pack_intro_message(),
            "reply_markup":json.dumps(self.review_markup,ensure_ascii=False,separators=(",",":")),
            "protect_content":"true" if protect_content else "false",
        })
        return int(result["message_id"])


def main() -> int:
    global CURRENT_STEP
    CURRENT_STEP="input_contract"
    token=str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    manifest_env=str(os.environ.get("BR_OWNER_AUDITION_MANIFEST_PATH") or "").strip()
    pack_id=str(os.environ.get("BR_OWNER_AUDITION_PACK_ID") or "").strip()
    receipt_env=str(os.environ.get("BR_OWNER_AUDITION_TERMINAL_RECEIPT") or "").strip()
    authority_ref=str(os.environ.get("BR_OWNER_AUDITION_AUTHORITY_REF") or "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN_NOT_MATERIALIZED")
    if not manifest_env:
        raise RuntimeError("OWNER_AUDITION_MANIFEST_PATH_NOT_PROPAGATED")
    if not pack_id or not receipt_env:
        raise RuntimeError("OWNER_AUDITION_EXPLICIT_HANDOFF_ENV_REQUIRED")

    CURRENT_STEP="audition_handoff"
    manifest_path=Path(manifest_env).resolve()
    manifest=consume_audition_handoff(manifest_path,expected_pack_id=pack_id)
    print("MANIFEST_EXISTS=PASS")
    print("MANIFEST_DIGEST=PASS")
    print("PACK_ID_MATCH=PASS")
    print("WORKSPACE_BINDING=PASS")
    for candidate in manifest["candidates"]:
        label=str(candidate["label"])
        print(f"CANDIDATE_{label}_EXISTS=PASS")
        print(f"CANDIDATE_{label}_HASH=PASS")
    print("AUDITION_HANDOFF=PASS")
    metadata=dict(manifest.get("metadata") or {})
    if (
        manifest.get("voice_identity_id")!="BR_OWNER_V1"
        or metadata.get("reference_source")!="TELEGRAM"
        or metadata.get("model_id")!=MODEL_ID
        or metadata.get("model_revision")!=MODEL_REVISION
        or metadata.get("provider_default_voice_used") is not False
        or metadata.get("provider_preset_voice_used") is not False
        or metadata.get("generic_voice_fallback") is not False
    ):
        raise RuntimeError("OWNER_AUDITION_HANDOFF_IDENTITY_CONTRACT_INVALID")

    CURRENT_STEP="reference_provenance"
    ref_index=_load_reference_index_from_environment()
    selected_id=int(metadata.get("selected_reference_input_id") or 0)
    source_row=next(
        (r for r in ref_index["references"] if int(r["telegram_input_id"])==selected_id),
        None,
    )
    if not isinstance(source_row,dict):
        raise RuntimeError("OWNER_AUDITION_REFERENCE_PROVENANCE_MISSING")
    chat_id=int(source_row["telegram_chat_id"])
    source_message_id=int(source_row["telegram_message_id"])

    CURRENT_STEP="machine_prescreen"
    workspace=Path(str(manifest["workspace"])).resolve()
    machine_qa_path=Path(
        str(os.environ.get("BR_OWNER_AUDITION_MACHINE_QA_PATH") or workspace/"machine-audition-qa.json")
    ).resolve()
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model
    stt_id=str(os.environ.get("BR_OWNER_STT_MODEL") or "large-v3-turbo").strip()
    stt_path=download_model(stt_id,output_dir=str(workspace/"stt-model-consumer"))
    stt=WhisperModel(str(stt_path),device="cpu",compute_type="int8",local_files_only=True)

    expected=str(metadata.get("audition_text") or "").strip()
    if not expected:
        raise RuntimeError("OWNER_AUDITION_EXPECTED_TEXT_MISSING")

    machine_qa=[]
    for row in manifest["candidates"]:
        source=Path(str(row["runtime_path"])).resolve()
        normalized=_normalize_for_qa(source,workspace/"qa"/f"{row['candidate_id']}.wav")
        metrics=pcm16_quality_metrics(normalized)
        segments_iter,info=stt.transcribe(
            str(normalized),language="pt",beam_size=5,vad_filter=True,
            word_timestamps=True,condition_on_previous_text=True,
        )
        segments=list(segments_iter)
        vad_speech_ratio=_vad_speech_occupancy(
            segments,
            float(metrics.get("duration_seconds") or 0.0),
        )
        observed=" ".join(
            str(getattr(seg,"text","") or "").strip()
            for seg in segments if str(getattr(seg,"text","") or "").strip()
        )
        pre={
            "candidate_id":str(row["candidate_id"]),
            "audio_sha256":str(row["sha256"]),
            "voice_identity_id":"BR_OWNER_V1",
            "provider_default_voice_used":False,
            "provider_preset_voice_used":False,
            "generic_voice_fallback":False,
            "detected_language":str(getattr(info,"language","pt") or "pt"),
            "language_probability":float(getattr(info,"language_probability",0.0) or 0.0),
            "vad_speech_ratio":vad_speech_ratio,
            "expected_text":expected,
            "observed_text":observed,
            "audio_metrics":metrics,
            "speaker_similarity":{
                "status":"PENDING_INDEPENDENT_VERIFIER",
                "score":None,
                "certifies_identity":False,
            },
            "transcription_confidence":_transcription_confidence(segments),
        }
        qa=evaluate_short_candidate(pre)
        machine_qa.append({**pre,**qa})
    sanitized_qa=_write_machine_qa(machine_qa_path,machine_qa)
    for row in machine_qa:
        _emit_sanitized_candidate_qa(row)
    if len(machine_qa)!=3 or any(row["eligible"] is not True for row in machine_qa):
        _write_machine_prescreen_failure_receipt(
            Path(receipt_env).resolve(),
            pack_id=pack_id,
            sanitized_qa=sanitized_qa,
        )
        raise RuntimeError("OWNER_AUDITION_MACHINE_PRESCREEN_FAILED")
    print("MACHINE_PRESCREEN=PASS")

    CURRENT_STEP="telegram_delivery"
    store=store_from_environment(repo_root=ROOT,workspace=workspace)
    ledger=GitBackedAuditionDeliveryLedger(store=store,pack_id=pack_id)
    ledger.create(
        manifest=manifest,
        telegram_chat_id=chat_id,
        real_reference_message_id=source_message_id,
        authority_ref=authority_ref,
    )
    api=TelegramAuditionApi(
        token=token,
        source_chat_id=chat_id,
        review_markup=build_pack_review_markup(),
    )
    result=deliver_owner_voice_audition_durable(api,ledger=ledger,manifest=manifest)
    receipt=ledger.sanitized_receipt(manifest=manifest)
    receipt_path=Path(receipt_env).resolve()
    receipt_path.parent.mkdir(parents=True,exist_ok=True)
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    if result.get("reconciliation_state")==SIDE_EFFECT_RECONCILIATION_REQUIRED:
        print("OWNER_AUDITION_DELIVERY=SIDE_EFFECT_RECONCILIATION_REQUIRED")
        raise RuntimeError("SIDE_EFFECT_RECONCILIATION_REQUIRED")
    if result.get("state")!="CONFIRMED":
        raise RuntimeError("OWNER_AUDITION_DELIVERY_NOT_CONFIRMED")

    ids=dict(result.get("confirmed_message_ids") or {})
    print("OWNER_VOICE_AUDITION_PACK="+pack_id)
    print("REAL_REFERENCE_SENT=PASS")
    print("CANDIDATE_A_SENT=PASS")
    print("CANDIDATE_B_SENT=PASS")
    print("CANDIDATE_C_SENT=PASS")
    print(f"REAL_REFERENCE_MESSAGE_ID={ids['reference']}")
    print("CANDIDATE_MESSAGE_IDS="+",".join(str(x) for x in ids["candidates"]))
    print(f"CONTROL_MESSAGE_ID={ids['control']}")
    print(f"REFERENCE_TELEGRAM_MESSAGE_ID={ids['reference']}")
    print(f"A_TELEGRAM_MESSAGE_ID={ids['candidates'][0]}")
    print(f"B_TELEGRAM_MESSAGE_ID={ids['candidates'][1]}")
    print(f"C_TELEGRAM_MESSAGE_ID={ids['candidates'][2]}")
    print(f"CONTROL_TELEGRAM_MESSAGE_ID={ids['control']}")
    print("AUDITION_DELIVERED_TO_TELEGRAM=PASS")
    print("HUMAN_REVIEW=PENDING")
    print("BR_OWNER_V1_RUNTIME_ACTIVATION=BLOCKED_PENDING_HUMAN_REVIEW")
    print("SHORTFORM_HUMAN_REVIEW=PENDING")
    print("LONGFORM_HUMAN_REVIEW=NOT_SENT")
    print("OWNER_VOICE_RUNTIME=BLOCKED_PENDING_HUMAN_REVIEW")
    print("BLIND_TELEGRAM_RETRY=0")
    print("RAW_OWNER_AUDIO_IN_PUBLIC_ARTIFACT=0")
    print("CLONE_AUDIO_IN_PUBLIC_ARTIFACT=0")
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        observed=" ".join(str(exc).split())[:500] or type(exc).__name__
        print(f"FAILED_STEP={CURRENT_STEP}",file=sys.stderr)
        print(f"FAILURE_CLASS={type(exc).__name__}",file=sys.stderr)
        print(f"EXPECTED={_EXPECTED_BY_STEP.get(CURRENT_STEP,'audition contract satisfied')}",file=sys.stderr)
        print(f"OBSERVED={observed}",file=sys.stderr)
        print(f"ROOT_CAUSE={type(exc).__name__}:{observed}",file=sys.stderr)
        print(f"NEXT_CAUSAL_ACTION={_NEXT_BY_STEP.get(CURRENT_STEP,'repair the causal failure and rerun from a clean explicit request')}",file=sys.stderr)
        print("OWNER_VOICE_HUMAN_AUDITION_PACK=FAIL",file=sys.stderr)
        raise
