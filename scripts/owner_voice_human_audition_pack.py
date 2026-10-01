from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from app.services.owner_voice_audio_quality_service import pcm16_quality_metrics
from app.services.owner_voice_human_audition_pack_service import (
    build_pack_intro_message,
    build_pack_review_markup,
    evaluate_short_candidate,
    select_blind_candidates,
)
from scripts.owner_voice_chatterbox_ptbr_audition import (
    MODEL_ID,
    MODEL_REVISION,
    _load_reference_index_from_environment,
)


def _sha256(path: Path) -> str:
    d=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            d.update(chunk)
    return d.hexdigest()


def _normalize_for_qa(source: Path,target: Path) -> Path:
    target.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run([
        "ffmpeg","-y","-v","error","-i",str(source),
        "-vn","-ac","1","-ar","16000","-c:a","pcm_s16le",str(target)
    ],check=True,capture_output=True)
    if not target.is_file() or target.stat().st_size<=0:
        raise RuntimeError("OWNER_AUDITION_QA_NORMALIZATION_FAILED")
    return target


def _to_voice_note(source: Path,target: Path) -> Path:
    target.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run([
        "ffmpeg","-y","-v","error","-i",str(source),
        "-vn","-ac","1","-ar","48000","-c:a","libopus","-b:a","64k",
        "-application","audio",str(target)
    ],check=True,capture_output=True)
    if not target.is_file() or target.stat().st_size<=0:
        raise RuntimeError("OWNER_AUDITION_VOICE_NOTE_FAILED")
    return target


def _telegram_post(token: str,method: str,*,data: Mapping[str,Any],files=None) -> dict[str,Any]:
    import requests
    response=requests.post(
        f"https://api.telegram.org/bot{token}/{method}",
        data=dict(data),files=files,timeout=180,
    )
    if response.status_code!=200:
        raise RuntimeError(f"TELEGRAM_{method.upper()}_FAILED")
    payload=response.json()
    if not isinstance(payload,dict) or payload.get("ok") is not True:
        raise RuntimeError(f"TELEGRAM_{method.upper()}_FAILED")
    return payload["result"]


def _send_message(token: str,chat_id: int,text: str,reply_markup: Mapping[str,Any]|None=None) -> int:
    data={"chat_id":str(chat_id),"text":text,"protect_content":"true"}
    if reply_markup is not None:
        data["reply_markup"]=json.dumps(dict(reply_markup),ensure_ascii=False,separators=(",",":"))
    result=_telegram_post(token,"sendMessage",data=data)
    return int(result["message_id"])


def _copy_real_reference(token: str,source_row: Mapping[str,Any]) -> int:
    chat_id=int(source_row["telegram_chat_id"])
    source_chat_id=int(source_row["telegram_chat_id"])
    source_message_id=int(source_row["telegram_message_id"])
    result=_telegram_post(token,"copyMessage",data={
        "chat_id":str(chat_id),
        "from_chat_id":str(source_chat_id),
        "message_id":str(source_message_id),
        "caption":"🎤 REFERÊNCIA REAL DO HUMANO — comparação de identidade BR_OWNER_V1",
        "protect_content":"true",
    })
    return int(result["message_id"])


def _send_voice(token: str,chat_id: int,path: Path,label: str) -> int:
    with path.open("rb") as stream:
        result=_telegram_post(token,"sendVoice",data={
            "chat_id":str(chat_id),
            "caption":f"🎙️ CANDIDATO {label} — prova cega BR_OWNER_V1",
            "protect_content":"true",
        },files={"voice":(f"BR_OWNER_V1_{label}.ogg",stream,"audio/ogg")})
    return int(result["message_id"])


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


def main() -> int:
    token=str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN_NOT_MATERIALIZED")
    temp=Path(os.environ.get("RUNNER_TEMP") or "/tmp").resolve()
    manifest_path=Path(os.environ.get("BR_OWNER_PTBR_AUDITION_SET") or temp/"br-owner-voice"/"ptbr-audition-set.json")
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("schema")!="OwnerVoicePtBrAuditionSet/v1"
        or manifest.get("voice_identity_id")!="BR_OWNER_V1"
        or manifest.get("reference_source")!="TELEGRAM"
        or manifest.get("model_id")!=MODEL_ID
        or manifest.get("model_revision")!=MODEL_REVISION
        or manifest.get("provider_default_voice_used") is not False
        or manifest.get("provider_preset_voice_used") is not False
        or manifest.get("generic_voice_fallback") is not False
    ):
        raise RuntimeError("OWNER_AUDITION_MANIFEST_INVALID")

    ref_index=_load_reference_index_from_environment()
    selected_id=int(manifest.get("selected_reference_input_id") or 0)
    source_row=next((r for r in ref_index["references"] if int(r["telegram_input_id"])==selected_id),None)
    if not isinstance(source_row,dict):
        raise RuntimeError("OWNER_AUDITION_REFERENCE_PROVENANCE_MISSING")
    chat_id=int(source_row["telegram_chat_id"])

    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model
    stt_id=str(os.environ.get("BR_OWNER_STT_MODEL") or "large-v3-turbo").strip()
    stt_path=download_model(stt_id,output_dir=str(temp/"br-owner-human-pack"/"stt-model"))
    stt=WhisperModel(str(stt_path),device="cpu",compute_type="int8",local_files_only=True)

    expected=str(manifest.get("audition_text") or "").strip()
    candidates=[]
    for output in manifest.get("outputs") or []:
        source=Path(str(output.get("path") or ""))
        if not source.is_file() or source.stat().st_size<=0:
            raise RuntimeError("OWNER_AUDITION_AUDIO_MISSING")
        normalized=_normalize_for_qa(source,temp/"br-owner-human-pack"/"qa"/f"candidate-{output['variant']}.wav")
        metrics=pcm16_quality_metrics(normalized)
        segments_iter,info=stt.transcribe(
            str(normalized),language="pt",beam_size=5,vad_filter=True,
            word_timestamps=True,condition_on_previous_text=True,
        )
        segments=list(segments_iter)
        observed=" ".join(
            str(getattr(seg,"text","") or "").strip()
            for seg in segments if str(getattr(seg,"text","") or "").strip()
        )
        pre={
            "candidate_id":f"candidate-{int(output['variant'])}",
            "audio_sha256":_sha256(source),
            "voice_identity_id":"BR_OWNER_V1",
            "provider_default_voice_used":False,
            "provider_preset_voice_used":False,
            "generic_voice_fallback":False,
            "detected_language":str(getattr(info,"language","pt") or "pt"),
            "language_probability":float(getattr(info,"language_probability",0.0) or 0.0),
            "expected_text":expected,
            "observed_text":observed,
            "audio_metrics":metrics,
            "speaker_similarity":{
                "status":"PENDING_INDEPENDENT_VERIFIER",
                "score":None,
                "certifies_identity":False,
            },
            "provider":MODEL_ID,
            "model_revision":MODEL_REVISION,
            "reference_sha256":str(output.get("reference_sha256") or ""),
            "parameters":{"cfg_weight":float(output["cfg_weight"])},
            "transcription_confidence":_transcription_confidence(segments),
            "path":str(source),
        }
        qa=evaluate_short_candidate(pre)
        candidates.append({**pre,**qa})

    pack_seed="|".join(sorted(c["audio_sha256"] for c in candidates))
    pack_id="BR_OWNER_V1_AUDITION_"+hashlib.sha256(pack_seed.encode()).hexdigest()[:16]
    public,private=select_blind_candidates(candidates,pack_id=pack_id)
    if len(public)<3:
        raise RuntimeError("OWNER_AUDITION_FEWER_THAN_THREE_ELIGIBLE_CANDIDATES")

    intro_message_id=_send_message(token,chat_id,build_pack_intro_message())
    real_reference_message_id=_copy_real_reference(token,source_row)

    sent=[]
    for row in public:
        private_row=private["mapping"][row["label"]]
        voice=_to_voice_note(
            Path(private_row["path"]),
            temp/"br-owner-human-pack"/"voice-notes"/f"{row['label']}.ogg",
        )
        message_id=_send_voice(token,chat_id,voice,row["label"])
        sent.append({**row,"telegram_message_id":message_id})

    control_message_id=_send_message(
        token,chat_id,
        "Escolha A, B, C ou rejeite todas pelo motivo principal. "
        "Aprovação aqui é apenas shortform; produção continua bloqueada até longform.",
        build_pack_review_markup(),
    )

    receipt={
        "schema_version":"OwnerVoiceHumanAuditionPack/v1",
        "pack_id":pack_id,
        "voice_identity_id":"BR_OWNER_V1",
        "real_reference":{"telegram_message_id":real_reference_message_id},
        "intro_message_id":intro_message_id,
        "control_message_id":control_message_id,
        "candidates":sent,
        "shortform_human_review":"PENDING",
        "longform_human_review":"NOT_SENT",
        "owner_voice_runtime":"BLOCKED_PENDING_HUMAN_REVIEW",
        "provider_mapping_persisted_in_public_receipt":False,
        "raw_owner_audio_in_git":0,
        "raw_owner_audio_in_public_artifact":0,
        "clone_audio_in_public_artifact":0,
    }
    receipt_path=Path(
        os.environ.get("BR_OWNER_AUDITION_PUBLIC_RECEIPT")
        or temp/"br-owner-audition-public"/"owner-voice-human-audition-pack.json"
    ).resolve()
    receipt_path.parent.mkdir(parents=True,exist_ok=True)
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    try: receipt_path.chmod(0o600)
    except OSError: pass

    print("OWNER_VOICE_AUDITION_PACK="+pack_id)
    print("REAL_REFERENCE_SENT=PASS")
    for row in sent:
        print(f"CANDIDATE_{row['label']}_SENT=PASS")
        print(f"CANDIDATE_{row['label']}_MESSAGE_ID={row['telegram_message_id']}")
        print(f"CANDIDATE_{row['label']}_SHA256={row['audio_sha256']}")
        print(f"CANDIDATE_{row['label']}_WER={row['word_error_rate']}")
        print(f"CANDIDATE_{row['label']}_CER={row['character_error_rate']}")
        print(f"CANDIDATE_{row['label']}_PT_PROB={row['language_probability']}")
    print(f"REAL_REFERENCE_MESSAGE_ID={real_reference_message_id}")
    print(f"INTRO_MESSAGE_ID={intro_message_id}")
    print(f"CONTROL_MESSAGE_ID={control_message_id}")
    print("SHORTFORM_HUMAN_REVIEW=PENDING")
    print("LONGFORM_HUMAN_REVIEW=NOT_SENT")
    print("OWNER_VOICE_RUNTIME=BLOCKED_PENDING_HUMAN_REVIEW")
    print("RAW_OWNER_AUDIO_IN_PUBLIC_ARTIFACT=0")
    print("CLONE_AUDIO_IN_PUBLIC_ARTIFACT=0")
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("OWNER_VOICE_HUMAN_AUDITION_PACK=FAIL FAILURE_CLASS="+str(exc).split(":",1)[0],file=sys.stderr)
        raise
