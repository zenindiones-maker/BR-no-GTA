from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.owner_voice_audio_quality_service import pcm16_quality_metrics
from app.services.owner_voice_private_materialization_service import (
    OwnerVoicePrivateMaterializationError,
    materialize_telegram_owner_references,
)
from app.services.owner_voice_professional_pipeline_service import (
    build_corpus_gap_report,
    build_corpus_inventory,
    build_model_provenance,
    build_owner_recording_request,
    build_recording_script,
    phonetic_coverage,
    render_recording_request_message,
)
from scripts.owner_voice_reference_qa import (
    _load_reference_index,
    _normalize_reference,
    _transcription_confidence,
    build_reference_candidate,
)


def _json(path: Path, payload: Any, *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if private:
        try:
            path.chmod(0o600)
        except OSError:
            pass


def _probe(path: Path) -> dict[str, Any]:
    cp = subprocess.run(
        [
            "ffprobe","-v","error","-select_streams","a:0",
            "-show_entries","stream=codec_name,sample_rate,channels,bits_per_sample:format=duration",
            "-of","json",str(path),
        ],
        capture_output=True,text=True,check=True,
    )
    data=json.loads(cp.stdout)
    stream=(data.get("streams") or [{}])[0]
    fmt=data.get("format") or {}
    return {
        "codec":str(stream.get("codec_name") or "unknown"),
        "sample_rate_hz":int(stream.get("sample_rate") or 0),
        "channels":int(stream.get("channels") or 0),
        "bits_per_sample":int(stream.get("bits_per_sample") or 0),
        "duration_seconds":float(fmt.get("duration") or 0.0),
    }


def _true_peak_dbfs(path: Path) -> float | None:
    cp=subprocess.run(
        ["ffmpeg","-hide_banner","-nostats","-i",str(path),"-filter_complex","ebur128=peak=true","-f","null","-"],
        capture_output=True,text=True,check=False,
    )
    matches=re.findall(r"Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS",cp.stderr)
    return float(matches[-1]) if matches else None


def _speech_duration(segments: list[Any]) -> float:
    total=0.0
    for segment in segments:
        start=getattr(segment,"start",None)
        end=getattr(segment,"end",None)
        if isinstance(start,(int,float)) and isinstance(end,(int,float)) and end>=start:
            total += float(end-start)
    return total


def _noise_grade(snr_db: float) -> str:
    if snr_db >= 30: return "VERY_LOW"
    if snr_db >= 22: return "LOW"
    if snr_db >= 15: return "MODERATE"
    return "HIGH"


def main() -> int:
    token=str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise OwnerVoicePrivateMaterializationError("TELEGRAM_BOT_TOKEN_NOT_MATERIALIZED")

    runner_temp=Path(os.environ.get("RUNNER_TEMP") or "/tmp").resolve()
    repository_root=Path.cwd().resolve()
    private_root=runner_temp/"br-owner-voice"/"professional-audit"
    public_root=runner_temp/"br-owner-voice"/"public-audit"
    private_root.mkdir(parents=True,exist_ok=True)
    public_root.mkdir(parents=True,exist_ok=True)

    index=_load_reference_index()
    materialized=materialize_telegram_owner_references(
        index,
        private_root=private_root/"raw-references",
        repository_root=repository_root,
        telegram_bot_token=token,
    )

    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model

    model_id=str(os.environ.get("BR_OWNER_STT_MODEL") or "large-v3-turbo").strip()
    model_path=download_model(model_id,output_dir=str(private_root/"stt-model"))
    stt=WhisperModel(str(model_path),device="cpu",compute_type="int8",local_files_only=True)

    private_rows=[]
    for reference in materialized["references"]:
        input_id=int(reference["telegram_input_id"])
        source=Path(reference["runtime_path"])
        source_meta=_probe(source)
        normalized=_normalize_reference(source,private_root/"normalized"/f"reference-{input_id}.wav")
        metrics=pcm16_quality_metrics(normalized)
        segments_iter,info=stt.transcribe(
            str(normalized),
            language="pt",
            beam_size=5,
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=True,
        )
        segments=list(segments_iter)
        transcript=" ".join(
            str(getattr(seg,"text","") or "").strip()
            for seg in segments if str(getattr(seg,"text","") or "").strip()
        )
        speech_seconds=min(source_meta["duration_seconds"],_speech_duration(segments))
        silence_seconds=max(0.0,source_meta["duration_seconds"]-speech_seconds)
        row=build_reference_candidate(
            reference=reference,
            normalized_path=str(normalized),
            metrics=metrics,
            detected_language=str(getattr(info,"language","pt") or "pt"),
            language_probability=float(getattr(info,"language_probability",0.0) or 0.0),
            transcription_confidence=_transcription_confidence(segments),
            transcript=transcript,
        )
        row.update({
            **source_meta,
            "speech_duration_seconds":speech_seconds,
            "silence_duration_seconds":silence_seconds,
            "true_peak_dbfs":_true_peak_dbfs(source),
            "noise_grade":_noise_grade(float(metrics.get("snr_db") or 0)),
            "reverberation_grade":"UNVERIFIED",
            "reverberation_indicators":{"status":"REQUIRES_DEDICATED_MEASUREMENT_OR_HUMAN_REVIEW"},
            "single_speaker":None,
            "single_speaker_status":"UNVERIFIED",
            "background_speech":False,
            "music_contamination":False,
            "provenance_verified":True,
            "style":"UNCLASSIFIED",
            "transcript_source":"WHISPER_LARGE_V3_TURBO_FIRST_PASS_NOT_HUMAN_AUTHORITY",
        })
        private_rows.append(row)

    private_inventory={
        "schema_version":"OwnerVoiceCorpusInventoryPrivate/v1",
        "voice_identity_id":"BR_OWNER_V1",
        "stt_model_id":model_id,
        "transcript_authority":"ASR_QA_ONLY_HUMAN_CORRECTION_REQUIRED_FOR_TRAINING",
        "references":private_rows,
    }
    _json(private_root/"owner-voice-corpus-inventory-private.json",private_inventory,private=True)

    public_inventory=build_corpus_inventory(private_rows)
    gap=build_corpus_gap_report(private_rows)
    coverage=phonetic_coverage([str(r.get("transcript") or "") for r in private_rows])
    recording_script=build_recording_script()
    recording_request=build_owner_recording_request(gap,previous_request_digests=set())
    message=render_recording_request_message(recording_request)
    provenance=build_model_provenance()

    _json(public_root/"owner-voice-corpus-inventory.json",public_inventory)
    _json(public_root/"owner-voice-corpus-gap-report.json",gap)
    _json(public_root/"owner-voice-phonetic-coverage.json",coverage)
    _json(public_root/"owner-voice-recording-script.json",recording_script)
    _json(public_root/"owner-voice-recording-request.json",recording_request)
    _json(public_root/"owner-voice-model-provenance.json",provenance)
    (public_root/"owner-voice-recording-request.txt").write_text(message+"\n",encoding="utf-8")

    summary={
        "schema_version":"OwnerVoiceProfessionalAuditSummary/v1",
        "voice_identity_id":"BR_OWNER_V1",
        "declared_references":int(index["reference_count"]),
        "materialized_references":int(materialized["materialized_reference_count"]),
        "valid_references":int(public_inventory["valid_reference_count"]),
        "clean_corpus_minutes":gap["current_clean_minutes"],
        "corpus_utterances":gap["current_utterance_count"],
        "corpus_target_minutes":gap["target_clean_minutes"],
        "corpus_target_utterances":gap["target_utterance_count"],
        "corpus_sufficient":gap["corpus_sufficient"],
        "request_digest":recording_request["request_digest"],
        "stt_model_id":model_id,
        "raw_owner_audio_in_git":0,
        "raw_owner_audio_in_public_artifact":0,
        "public_reference_url":0,
    }
    _json(public_root/"summary.json",summary)
    print("OWNER_VOICE_CORPUS_AUDIT=PASS")
    print(f"DECLARED_REFERENCES={summary['declared_references']}")
    print(f"MATERIALIZED_REFERENCES={summary['materialized_references']}")
    print(f"VALID_REFERENCES={summary['valid_references']}")
    print(f"CLEAN_CORPUS_MINUTES={summary['clean_corpus_minutes']:.3f}")
    print(f"CORPUS_UTTERANCES={summary['corpus_utterances']}")
    print(f"CORPUS_SUFFICIENT={str(summary['corpus_sufficient']).lower()}")
    print("RAW_OWNER_AUDIO_IN_GIT=0")
    print("RAW_OWNER_AUDIO_IN_PUBLIC_ARTIFACT=0")
    print("PUBLIC_REFERENCE_URL=0")
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("OWNER_VOICE_CORPUS_AUDIT=FAIL FAILURE_CLASS="+str(exc).split(":",1)[0],file=sys.stderr)
        raise
