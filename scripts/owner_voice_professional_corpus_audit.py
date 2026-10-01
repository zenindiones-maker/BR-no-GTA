from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from app.services.owner_voice_audio_quality_service import pcm16_quality_metrics
from app.services.owner_voice_private_materialization_service import (
    OwnerVoicePrivateMaterializationError,
    materialize_telegram_owner_references,
)
from app.services.owner_voice_professional_pipeline_service import (
    build_corpus_gap_report,
    build_corpus_inventory,
    build_corpus_revision,
    build_owner_recording_request,
    build_recording_script,
    phonetic_coverage,
    render_recording_request_message,
)
from scripts.owner_voice_reference_qa import (
    _load_reference_index,
    _transcription_confidence,
)


def _ffprobe(path: Path) -> dict[str, Any]:
    cp=subprocess.run(
        ["ffprobe","-v","error","-select_streams","a:0","-show_entries",
         "stream=codec_name,sample_rate,channels,bits_per_sample","-show_entries","format=duration",
         "-of","json",str(path)],
        capture_output=True,text=True,check=True,
    )
    payload=json.loads(cp.stdout)
    stream=(payload.get("streams") or [{}])[0]
    fmt=payload.get("format") or {}
    return {
        "codec":str(stream.get("codec_name") or "unknown"),
        "source_sample_rate_hz":int(stream.get("sample_rate") or 0),
        "source_channels":int(stream.get("channels") or 0),
        "source_bits_per_sample":int(stream.get("bits_per_sample") or 0),
        "source_duration_seconds":float(fmt.get("duration") or 0.0),
    }


def _normalize(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(
        ["ffmpeg","-y","-v","error","-i",str(source),"-vn","-ac","1","-ar","16000","-c:a","pcm_s16le",str(target)],
        capture_output=True,check=True,
    )
    if not target.is_file() or target.stat().st_size<=0:
        raise RuntimeError("OWNER_REFERENCE_NORMALIZATION_FAILED")
    return target


def _noise_grade(snr: float) -> str:
    if snr >= 30: return "LOW"
    if snr >= 20: return "MODERATE"
    if snr >= 12: return "HIGH"
    return "SEVERE"


def _reverb_indicator(metrics: dict[str, Any]) -> str:
    # Conservative initial indicator only. Human/acoustic review remains authoritative.
    silence=float(metrics.get("silence_ratio") or 0)
    snr=float(metrics.get("snr_db") or 0)
    if snr>=25 and silence<=0.45: return "LOW_INDICATOR"
    if snr>=15: return "MODERATE_INDICATOR"
    return "HIGH_INDICATOR"


def main() -> int:
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model

    token=str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise OwnerVoicePrivateMaterializationError("TELEGRAM_BOT_TOKEN_NOT_MATERIALIZED")

    root=Path.cwd().resolve()
    temp=Path(os.environ.get("RUNNER_TEMP") or "/tmp").resolve()/ "br-owner-professional-audit"
    private_root=temp/"references"
    private_out=temp/"private"
    public_out=Path(os.environ.get("BR_OWNER_PROFESSIONAL_PUBLIC_OUT") or temp/"public").resolve()
    private_out.mkdir(parents=True,exist_ok=True)
    public_out.mkdir(parents=True,exist_ok=True)

    index=_load_reference_index()
    materialized=materialize_telegram_owner_references(
        index,private_root=private_root,repository_root=root,telegram_bot_token=token
    )

    model_id=str(os.environ.get("BR_OWNER_STT_MODEL") or "large-v3").strip()
    model_root=temp/"stt-model"
    model_path=download_model(model_id,output_dir=str(model_root))
    stt=WhisperModel(str(model_path),device="cpu",compute_type="int8",local_files_only=True)

    rows=[]
    for ref in materialized["references"]:
        input_id=int(ref["telegram_input_id"])
        source=Path(ref["runtime_path"])
        source_info=_ffprobe(source)
        normalized=_normalize(source,temp/"normalized"/f"reference-{input_id}.wav")
        metrics=pcm16_quality_metrics(normalized)
        segments_iter,info=stt.transcribe(
            str(normalized),language=None,beam_size=5,vad_filter=True,
            word_timestamps=True,condition_on_previous_text=True,
        )
        segments=list(segments_iter)
        transcript=" ".join(
            str(getattr(seg,"text","") or "").strip()
            for seg in segments if str(getattr(seg,"text","") or "").strip()
        )
        speech_seconds=float(metrics["duration_seconds"])*(1.0-float(metrics["silence_ratio"]))
        pt_prob=float(getattr(info,"language_probability",0.0) or 0.0) if str(getattr(info,"language","") or "").lower()=="pt" else 0.0
        row={
            "telegram_input_id":input_id,
            "private_audio_ref":ref["private_audio_ref"],
            "sha256":ref["sha256"],
            "duration_seconds":float(metrics["duration_seconds"]),
            "speech_duration_seconds":speech_seconds,
            "silence_duration_seconds":max(0.0,float(metrics["duration_seconds"])-speech_seconds),
            "codec":source_info["codec"],
            "sample_rate_hz":source_info["source_sample_rate_hz"],
            "channels":source_info["source_channels"],
            "bits_per_sample":source_info["source_bits_per_sample"],
            "single_speaker":None,
            "single_speaker_status":"PENDING_SPEAKER_VERIFICATION",
            "clipping_ratio":float(metrics["clipping_ratio"]),
            "peak_dbfs":float(metrics["peak_dbfs"]),
            "rms_dbfs":float(metrics["rms_dbfs"]),
            "snr_db":float(metrics["snr_db"]),
            "noise_grade":_noise_grade(float(metrics["snr_db"])),
            "reverberation_grade":_reverb_indicator(metrics),
            "ptbr_probability":pt_prob,
            "detected_language":str(getattr(info,"language","") or ""),
            "transcript":transcript,
            "transcript_status":"ASR_FIRST_PASS_NOT_HUMAN_AUTHORITY",
            "utterance_count":len(segments),
            "transcript_confidence":_transcription_confidence(segments),
            "style":"UNCLASSIFIED",
            "background_speech":False,
            "music_contamination":False,
            "provenance_verified":True,
        }
        rows.append(row)

    private_inventory={
        "schema_version":"OwnerVoiceCorpusInventoryPrivate/v1",
        "voice_identity_id":"BR_OWNER_V1",
        "stt_model_id":model_id,
        "reference_index_sha256":index["index_sha256"],
        "references":rows,
    }
    (private_out/"owner-voice-corpus-inventory-private.json").write_text(
        json.dumps(private_inventory,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8"
    )
    (private_out/"owner-voice-corpus-inventory-private.json").chmod(0o600)

    public_inventory=build_corpus_inventory(rows)
    public_inventory["declared_reference_count"]=int(index["reference_count"])
    public_inventory["stt_model_id"]=model_id
    public_inventory["reference_index_sha256"]=index["index_sha256"]
    gap=build_corpus_gap_report(rows)
    coverage=phonetic_coverage([r["transcript"] for r in rows])
    corpus_revision=build_corpus_revision(rows,revision="BR_OWNER_V1_CORPUS/audit-001")
    recording_script=build_recording_script()

    previous=set()
    request=build_owner_recording_request(gap,previous_request_digests=previous)
    request_message=render_recording_request_message(request)
    request_public={**request,"message_digest":hashlib.sha256(request_message.encode("utf-8")).hexdigest()}

    outputs={
        "owner-voice-corpus-inventory-v1.json":public_inventory,
        "owner-voice-corpus-gap-report-v1.json":gap,
        "owner-voice-phonetic-coverage-v1.json":coverage,
        "owner-voice-corpus-revision-v1.json":corpus_revision,
        "owner-voice-recording-script-v1.json":recording_script,
        "owner-voice-recording-request-v1.json":request_public,
    }
    for name,payload in outputs.items():
        (public_out/name).write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")

    # Message body remains private to runtime until delivery; artifact gets digest only.
    (private_out/"owner-voice-recording-request-message.txt").write_text(request_message+"\n",encoding="utf-8")
    (private_out/"owner-voice-recording-request-message.txt").chmod(0o600)

    print(f"OWNER_CORPUS_DECLARED_REFERENCES={index['reference_count']}")
    print(f"OWNER_CORPUS_MATERIALIZED_REFERENCES={materialized['materialized_reference_count']}")
    print(f"OWNER_CORPUS_VALID_REFERENCES={public_inventory['valid_reference_count']}")
    print(f"OWNER_CORPUS_CLEAN_MINUTES={gap['current_clean_minutes']:.6f}")
    print(f"OWNER_CORPUS_UTTERANCES={gap['current_utterance_count']}")
    print(f"OWNER_CORPUS_SUFFICIENT={str(gap['corpus_sufficient']).lower()}")
    print(f"OWNER_RECORDING_REQUEST_DIGEST={request['request_digest']}")
    print(f"OWNER_STT_MODEL={model_id}")
    print("RAW_OWNER_AUDIO_IN_PUBLIC_ARTIFACT=0")
    print("OWNER_TRANSCRIPT_IN_PUBLIC_ARTIFACT=0")
    print("OWNER_PROFESSIONAL_CORPUS_AUDIT=PASS")
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            "OWNER_PROFESSIONAL_CORPUS_AUDIT=FAIL "
            f"FAILURE_CLASS={type(exc).__name__}",
            file=__import__("sys").stderr,
        )
        raise
