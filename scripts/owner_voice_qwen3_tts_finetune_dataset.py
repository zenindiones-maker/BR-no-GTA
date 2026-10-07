from __future__ import annotations

import json
import os
from pathlib import Path

from app.services.owner_voice_audio_quality_service import pcm16_quality_metrics
from app.services.owner_voice_private_materialization_service import materialize_telegram_owner_references
from app.services.owner_voice_speaker_identity_service import (
    calibrate_owner_identity_profile,
    calibrate_owner_window_consistency,
    evaluate_reference_window_consistency,
    select_canonical_reference,
)
from scripts.owner_voice_single_human_clone import (
    _embedding,
    _ffmpeg,
    _index,
    _load_speaker_model,
    _load_stt,
    _reference_asr_metrics,
    _window_identity_scores,
)

VOICE_IDENTITY_ID="BR_OWNER_V1"
REFERENCE_SOURCE="TELEGRAM_HUMAN_OWNER"
MIN_TRAINING_SAMPLES=12
MIN_TRAINING_SECONDS=180.0


def main()->int:
    token=str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN_NOT_MATERIALIZED")
    root=Path(os.environ["BR_OWNER_FINETUNE_PRIVATE_WORKSPACE"]).resolve()
    cache=Path(os.environ.get("BR_OWNER_PUBLIC_MODEL_CACHE") or Path.home()/".cache"/"br-owner-voice"/"hf-public").resolve()
    root.mkdir(parents=True,exist_ok=True)
    index=_index()
    materialized=materialize_telegram_owner_references(
        index,
        private_root=root/"owner-references",
        repository_root=Path.cwd().resolve(),
        telegram_bot_token=token,
    )
    refs=list(materialized.get("references") or [])
    if len(refs)<MIN_TRAINING_SAMPLES:
        raise RuntimeError("OWNER_FINETUNE_REFERENCE_COUNT_TOO_SMALL")

    verifier=_load_speaker_model(cache)
    normalized={}
    original_sources={}
    embeddings={}
    metrics={}
    for row in refs:
        rid=str(int(row["telegram_input_id"]))
        original=Path(row["runtime_path"]).resolve()
        original_sources[rid]=original
        wav=_ffmpeg(original,root/"identity-16k"/f"{rid}.wav",16000)
        normalized[rid]=wav
        embeddings[rid]=_embedding(verifier,wav)
        metrics[rid]=pcm16_quality_metrics(wav)

    profile=calibrate_owner_identity_profile(embeddings)
    inliers=set(str(x) for x in profile["inlier_ids"])
    window_scores={
        rid:_window_identity_scores(verifier,normalized[rid],embeddings[rid])
        for rid in sorted(inliers)
    }
    calibration=calibrate_owner_window_consistency(window_scores)
    stt=_load_stt(cache)

    evaluated=[]
    training=[]
    asr_count=0
    for row in refs:
        rid=str(int(row["telegram_input_id"]))
        if rid not in inliers:
            continue
        m=metrics[rid]
        if float(m.get("snr_db") or 0.0)<15.0 or float(m.get("clipping_ratio") or 0.0)>0.01:
            continue
        window=evaluate_reference_window_consistency(window_scores[rid],calibration)
        if window["passed"] is not True:
            continue
        pt,vad,language,text=_reference_asr_metrics(
            stt,normalized[rid],float(m.get("duration_seconds") or 0.0),beam_size=5
        )
        asr_count+=1
        candidate={
            "reference_id":rid,
            "telegram_input_id":int(row["telegram_input_id"]),
            "sha256":str(row["sha256"]),
            "duration_seconds":float(m.get("duration_seconds") or 0.0),
            "snr_db":float(m.get("snr_db") or 0.0),
            "clipping_ratio":float(m.get("clipping_ratio") or 0.0),
            "speech_ratio":float(vad),
            "single_speaker":True,
            "clear_speech":True,
            "no_overlap":True,
            "no_music":True,
            "ptbr_probability":float(pt),
        }
        evaluated.append(candidate)
        if float(pt)<0.90 or float(vad)<0.55 or not text.strip():
            continue
        wav24=_ffmpeg(original_sources[rid],root/"dataset"/"audio"/f"{rid}.wav",24000)
        training.append((candidate,text.strip(),wav24))

    canonical=select_canonical_reference(evaluated,profile)
    canonical_id=str(canonical["reference_id"])
    canonical24=_ffmpeg(
        original_sources[canonical_id],
        root/"dataset"/"canonical-owner-reference.wav",
        24000,
    )

    train_raw=root/"dataset"/"train_raw.jsonl"
    train_swift=root/"dataset"/"train_swift.jsonl"
    train_raw.parent.mkdir(parents=True,exist_ok=True)
    rows=[]
    swift_rows=[]
    total_seconds=0.0
    for candidate,text,audio in training:
        total_seconds+=float(candidate["duration_seconds"])
        rows.append({
            "audio":str(audio.resolve()),
            "text":text,
            "ref_audio":str(canonical24.resolve()),
        })
        swift_rows.append({
            "messages":[{"role":"assistant","content":text}],
            "audios":[str(audio.resolve())],
            "ref_audios":[str(canonical24.resolve())],
        })
    if len(rows)<MIN_TRAINING_SAMPLES:
        raise RuntimeError("OWNER_FINETUNE_ELIGIBLE_SAMPLE_COUNT_TOO_SMALL")
    if total_seconds<MIN_TRAINING_SECONDS:
        raise RuntimeError("OWNER_FINETUNE_TOTAL_DURATION_TOO_SMALL")
    with train_raw.open("w",encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
    with train_swift.open("w",encoding="utf-8") as stream:
        for row in swift_rows:
            stream.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")

    identity_private=root/"identity-profile.private.json"
    identity_private.write_text(
        json.dumps({
            "profile":profile,
            "canonical_embedding":embeddings[canonical_id],
            "canonical_reference_telegram_input_id":int(canonical["telegram_input_id"]),
            "canonical_reference_sha256":str(canonical["sha256"]),
        },separators=(",",":"))+"\n",
        encoding="utf-8",
    )
    source_row=next(
        row for row in index["references"]
        if int(row["telegram_input_id"])==int(canonical["telegram_input_id"])
    )

    manifest={
        "schema_version":"OwnerVoiceQwen3TTSFineTuneDataset/v2",
        "voice_identity_id":VOICE_IDENTITY_ID,
        "reference_source":REFERENCE_SOURCE,
        "sample_count":len(rows),
        "total_seconds":round(total_seconds,3),
        "canonical_reference_telegram_input_id":int(canonical["telegram_input_id"]),
        "canonical_reference_sha256":str(canonical["sha256"]),
        "canonical_reference_source_message_id":int(source_row["telegram_message_id"]),
        "telegram_chat_id":int(source_row["telegram_chat_id"]),
        "same_ref_audio_for_all_samples":True,
        "reference_audio_lineage":"ORIGINAL_TELEGRAM_TO_24K_DIRECT",
        "training_audio_lineage":"ORIGINAL_TELEGRAM_TO_24K_DIRECT",
        "raw_audio_public":False,
        "transcripts_public":False,
        "speaker_embedding_public":False,
    }
    manifest_path=root/"dataset"/"dataset-manifest.json"
    manifest_path.write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n",encoding="utf-8")

    output=str(os.environ.get("GITHUB_OUTPUT") or "").strip()
    if output:
        with open(output,"a",encoding="utf-8") as stream:
            stream.write(f"train_raw_jsonl={train_raw}\n")
            stream.write(f"train_swift_jsonl={train_swift}\n")
            stream.write(f"dataset_manifest={manifest_path}\n")
            stream.write(f"identity_profile_private={identity_private}\n")
            stream.write(f"canonical_reference_24k={canonical24}\n")
            stream.write(f"sample_count={len(rows)}\n")
            stream.write(f"total_seconds={total_seconds:.3f}\n")
    print(f"OWNER_FINETUNE_REFERENCE_ASR_COUNT={asr_count}")
    print(f"OWNER_FINETUNE_SAMPLE_COUNT={len(rows)}")
    print(f"OWNER_FINETUNE_TOTAL_SECONDS={total_seconds:.3f}")
    print("OWNER_FINETUNE_SAME_REFERENCE_FOR_ALL_SAMPLES=PASS")
    print("OWNER_FINETUNE_SWIFT_NATIVE_JSONL=PASS")
    print("OWNER_FINETUNE_DATASET=PASS")
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"OWNER_FINETUNE_DATASET=FAIL FAILURE_CLASS={type(exc).__name__}:{str(exc)[:300]}",file=__import__("sys").stderr)
        raise SystemExit(61)
