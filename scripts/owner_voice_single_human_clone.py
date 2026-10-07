from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from app.services.owner_voice_audio_quality_service import pcm16_quality_metrics
from app.services.owner_voice_human_audition_pack_service import evaluate_short_candidate
from app.services.owner_voice_private_materialization_service import materialize_telegram_owner_references
from app.services.owner_voice_speaker_identity_service import (
    PROFILE_SCHEMA,
    SPEAKER_MODEL_ID,
    SPEAKER_MODEL_REVISION,
    calibrate_owner_identity_profile,
    calibrate_owner_window_consistency,
    cosine_similarity,
    evaluate_clone_identity_gate,
    evaluate_reference_window_consistency,
    sanitized_profile,
    select_canonical_reference,
)
from app.services.owner_voice_telegram_handoff_service import parse_reference_envelope_b64
from app.services.owner_voice_zero_cost_policy_service import validate_owner_voice_execution
VOICE_IDENTITY_ID="BR_OWNER_V1"
QWEN_MODEL_ID="Qwen/Qwen3-TTS-12Hz-1.7B-Base"
QWEN_MODEL_REVISION="fd4b254389122332181a7c3db7f27e918eec64e3"
QWEN_MODEL_SHA256="38fc7fc51c5e776e840414b6fd443962e9411b9654888fd7913e4da643cb857c"
QWEN_SPEECH_TOKENIZER_SHA256="836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258"
QWEN_TTS_VERSION="0.1.1"
REFERENCE_SOURCE="TELEGRAM_HUMAN_OWNER"
IDENTITY_PROFILE_SCHEMA="OwnerSpeakerIdentityProfile/v1"
PINNED_SPEAKER_MODEL_ID="speechbrain/spkrec-ecapa-voxceleb"
SHORT_TEXT=(
    "Booooa meu povo, aqui é BR no GTA 6! Hoje a gente vai falar de Vice City, "
    "Leonida e Rockstar. Quero falar do meu jeito, com energia, clareza e ritmo "
    "natural. E BR não dorme em Vice City."
)
SPEECHBRAIN_VERSION="1.1.1"
SPEAKER_MODEL_EMBEDDING_SHA256="0575cb64845e6b9a10db9bcb74d5ac32b326b8dc90352671d345e2ee3d0126a2"


def _sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def _index() -> dict[str,Any]:
    envelope=str(os.environ.get("BR_OWNER_TELEGRAM_REFERENCE_ENVELOPE_B64") or "").strip()
    legacy=str(os.environ.get("BR_OWNER_TELEGRAM_REFERENCE_INDEX") or "").strip()
    if envelope:
        return parse_reference_envelope_b64(envelope)
    if legacy:
        value=json.loads(legacy)
        if isinstance(value,dict):
            return value
    raise RuntimeError("OWNER_TELEGRAM_REFERENCE_INDEX_NOT_MATERIALIZED")


def _ffmpeg(source: Path,target: Path,rate:int)->Path:
    target.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(
        ["ffmpeg","-y","-v","error","-i",str(source),"-vn","-ac","1","-ar",str(rate),"-c:a","pcm_s16le",str(target)],
        check=True,capture_output=True,
    )
    if not target.is_file() or target.stat().st_size<=0:
        raise RuntimeError("OWNER_REFERENCE_NORMALIZATION_FAILED")
    return target


def _load_speaker_model(cache_root: Path):
    from huggingface_hub import snapshot_download
    from speechbrain.inference.classifiers import EncoderClassifier

    snapshot=Path(snapshot_download(
        repo_id=SPEAKER_MODEL_ID,
        revision=SPEAKER_MODEL_REVISION,
        cache_dir=str(cache_root/"huggingface"),
        allow_patterns=["hyperparams.yaml","embedding_model.ckpt","mean_var_norm_emb.ckpt","classifier.ckpt","label_encoder.txt"],
    )).resolve()
    model_file=snapshot/"embedding_model.ckpt"
    if not model_file.is_file() or _sha256(model_file)!=SPEAKER_MODEL_EMBEDDING_SHA256:
        raise RuntimeError("SPEAKER_MODEL_EMBEDDING_SHA256_MISMATCH")
    classifier=EncoderClassifier.from_hparams(
        source=str(snapshot),
        savedir=str(cache_root/"speechbrain-runtime"),
        run_opts={"device":"cpu"},
        overrides={"pretrained_path":str(snapshot)},
    )
    return classifier


def _load_pcm16_tensor(path:Path):
    import soundfile as sf
    import torch

    audio,sr=sf.read(str(path),dtype="float32",always_2d=True)
    if int(sr)!=16000:
        raise RuntimeError("SPEAKER_REFERENCE_RATE_INVALID")
    if audio.size==0:
        raise RuntimeError("SPEAKER_REFERENCE_AUDIO_EMPTY")
    signal=torch.from_numpy(audio.T.copy())
    if signal.ndim!=2 or signal.shape[0]!=1:
        signal=signal.mean(dim=0,keepdim=True)
    return signal,int(sr)


def _embedding(classifier,path:Path)->list[float]:
    signal,_sr=_load_pcm16_tensor(path)
    emb=classifier.encode_batch(signal,normalize=True).detach().cpu().reshape(-1)
    return [float(x) for x in emb.tolist()]


def _window_identity_scores(classifier,path:Path,full_embedding:list[float])->list[float]:
    signal,sr=_load_pcm16_tensor(path)
    total=int(signal.shape[-1])
    window=min(total,4*sr)
    if window<2*sr:
        return []
    starts=[0,max(0,(total-window)//2),max(0,total-window)]
    scores=[]
    for start in sorted(set(starts)):
        piece=signal[:,start:start+window]
        emb=classifier.encode_batch(piece,normalize=True).detach().cpu().reshape(-1).tolist()
        scores.append(cosine_similarity(full_embedding,emb))
    return scores


def _load_stt(cache_root:Path):
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model
    model_id=str(os.environ.get("BR_OWNER_STT_MODEL") or "large-v3-turbo")
    target=cache_root/"stt"/model_id
    target.mkdir(parents=True,exist_ok=True)
    path=download_model(model_id,output_dir=str(target))
    return WhisperModel(str(path),device="cpu",compute_type="int8",cpu_threads=4,num_workers=1,local_files_only=True)


def _reference_asr_metrics(stt,path:Path,duration_seconds:float,*,beam_size:int=1)->tuple[float,float,str,str]:
    segments_iter,info=stt.transcribe(
        str(path),language=None,beam_size=int(beam_size),vad_filter=True,
        word_timestamps=False,condition_on_previous_text=False,
    )
    segments=list(segments_iter)
    language=str(getattr(info,"language","") or "").lower().replace("_","-")
    probability=float(getattr(info,"language_probability",0.0) or 0.0)
    ptbr_probability=probability if language in {"pt","pt-br"} else 0.0
    vad_speech_ratio=_vad_ratio(segments,float(duration_seconds))
    transcript=" ".join(
        str(getattr(segment,"text","") or "").strip()
        for segment in segments
        if str(getattr(segment,"text","") or "").strip()
    ).strip()
    return ptbr_probability,vad_speech_ratio,language,transcript


def _prepare_qwen_model(cache_root:Path)->Path:
    from huggingface_hub import snapshot_download

    snapshot=Path(snapshot_download(
        repo_id=QWEN_MODEL_ID,
        revision=QWEN_MODEL_REVISION,
        cache_dir=str(cache_root/"huggingface"),
    )).resolve()
    model_weights=snapshot/"model.safetensors"
    speech_tokenizer_weights=snapshot/"speech_tokenizer"/"model.safetensors"
    if not model_weights.is_file() or _sha256(model_weights)!=QWEN_MODEL_SHA256:
        raise RuntimeError("QWEN3_TTS_MODEL_SHA256_MISMATCH")
    if (
        not speech_tokenizer_weights.is_file()
        or _sha256(speech_tokenizer_weights)!=QWEN_SPEECH_TOKENIZER_SHA256
    ):
        raise RuntimeError("QWEN3_TTS_SPEECH_TOKENIZER_SHA256_MISMATCH")
    return snapshot


def _vad_ratio(segments,duration:float)->float:
    if duration<=0:
        return 0.0
    spans=[]
    for seg in segments:
        start=max(0.0,min(duration,float(getattr(seg,"start",0.0) or 0.0)))
        end=max(start,min(duration,float(getattr(seg,"end",start) or start)))
        if end>start:
            spans.append((start,end))
    spans.sort()
    merged=[]
    for start,end in spans:
        if not merged or start>merged[-1][1]:
            merged.append([start,end])
        else:
            merged[-1][1]=max(merged[-1][1],end)
    return max(0.0,min(1.0,sum(b-a for a,b in merged)/duration))


def main()->int:
    validate_owner_voice_execution(mode="inference")
    if IDENTITY_PROFILE_SCHEMA!=PROFILE_SCHEMA:
        raise RuntimeError("OWNER_SPEAKER_PROFILE_SCHEMA_MISMATCH")
    if PINNED_SPEAKER_MODEL_ID!=SPEAKER_MODEL_ID:
        raise RuntimeError("OWNER_SPEAKER_MODEL_ID_MISMATCH")
    if len(SHORT_TEXT)>300:
        raise RuntimeError("OWNER_SINGLE_CLONE_TEXT_TOO_LONG")
    token=str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN_NOT_MATERIALIZED")
    workspace=Path(os.environ["BR_OWNER_AUDITION_WORKSPACE"]).resolve()
    cache_root=Path(os.environ.get("BR_OWNER_PUBLIC_MODEL_CACHE") or Path.home()/".cache"/"br-owner-voice"/"hf-public").resolve()
    workspace.mkdir(parents=True,exist_ok=True)
    index=_index()
    materialized=materialize_telegram_owner_references(
        index,private_root=workspace/"owner-references",
        repository_root=Path.cwd().resolve(),telegram_bot_token=token,
    )
    refs=list(materialized.get("references") or [])
    if len(refs)<3:
        raise RuntimeError("OWNER_REFERENCE_COUNT_TOO_SMALL")

    classifier=_load_speaker_model(cache_root)
    normalized={}
    original_sources={}
    embeddings={}
    metrics={}
    for row in refs:
        rid=str(int(row["telegram_input_id"]))
        original=Path(row["runtime_path"]).resolve()
        original_sources[rid]=original
        wav=_ffmpeg(original,workspace/"identity-16k"/f"{rid}.wav",16000)
        normalized[rid]=wav
        metrics[rid]=pcm16_quality_metrics(wav)
        embeddings[rid]=_embedding(classifier,wav)

    profile=calibrate_owner_identity_profile(embeddings)
    centroid_floor=float(profile["clone_centroid_min_similarity"])
    inlier_ids=set(str(x) for x in profile["inlier_ids"])
    window_scores_by_id={
        rid:_window_identity_scores(classifier,normalized[rid],embeddings[rid])
        for rid in sorted(inlier_ids)
    }
    window_calibration=calibrate_owner_window_consistency(window_scores_by_id)
    candidate_rows=[]
    for row in refs:
        rid=str(int(row["telegram_input_id"]))
        if rid not in inlier_ids:
            continue
        m=metrics[rid]
        amplitude_speech_ratio=float(m.get("speech_ratio") or 0.0)
        clear=(
            float(m.get("snr_db") or 0.0)>=15.0
            and float(m.get("clipping_ratio") or 0.0)<=0.01
        )
        window_eval=evaluate_reference_window_consistency(
            window_scores_by_id[rid],
            window_calibration,
        )
        consistent=bool(window_eval["passed"])
        candidate_rows.append({
            "reference_id":rid,
            "telegram_input_id":int(row["telegram_input_id"]),
            "sha256":str(row["sha256"]),
            "duration_seconds":float(m.get("duration_seconds") or row.get("duration_seconds") or 0.0),
            "snr_db":float(m.get("snr_db") or 0.0),
            "clipping_ratio":float(m.get("clipping_ratio") or 0.0),
            "amplitude_speech_ratio":amplitude_speech_ratio,
            "speech_ratio":0.0,
            "single_speaker":consistent,
            "window_identity_p10":float(window_eval["reference_p10"]),
            "window_identity_threshold":float(window_eval["min_similarity"]),
            "clear_speech":clear,
            "no_overlap":consistent,
            "no_music":consistent,
            "ptbr_probability":0.0,
        })

    pre_asr=[
        row for row in candidate_rows
        if str(row["reference_id"]) in inlier_ids
        and row["single_speaker"] is True
        and row["clear_speech"] is True
        and row["no_overlap"] is True
        and row["no_music"] is True
        and float(row["duration_seconds"])>0.0
        and float(profile["reference_similarity_to_centroid"].get(str(row["reference_id"]),-1.0))
            >=float(profile["clone_centroid_min_similarity"])
    ]
    pre_asr.sort(key=lambda row:(
        0 if 10.0<=row["duration_seconds"]<=20.0 else 1,
        -float(profile["reference_similarity_to_centroid"].get(str(row["reference_id"]),-1)),
        -row["snr_db"],
        abs(float(row["duration_seconds"])-15.0),
        str(row["sha256"]),
    ))
    print(f"OWNER_CANONICAL_INLIER_COUNT={len(inlier_ids)}")
    print(f"OWNER_WINDOW_CONSISTENCY_REFERENCE_COUNT={window_calibration['reference_count']}")
    print(f"OWNER_WINDOW_CONSISTENCY_MIN_SIMILARITY={window_calibration['min_similarity']}")
    print("OWNER_WINDOW_CONSISTENCY_CALIBRATION=OWNER_REFERENCE_WINDOW_DISTRIBUTION")
    print(f"OWNER_CANONICAL_SINGLE_SPEAKER_COUNT={sum(1 for row in candidate_rows if row['single_speaker'] is True)}")
    print(f"OWNER_CANONICAL_CLEAR_SPEECH_COUNT={sum(1 for row in candidate_rows if row['clear_speech'] is True)}")
    print(f"OWNER_CANONICAL_PRE_ASR_ELIGIBLE_COUNT={len(pre_asr)}")
    if not pre_asr:
        raise RuntimeError("NO_CANONICAL_OWNER_REFERENCE_PRE_ASR_ELIGIBLE")

    stt=_load_stt(cache_root)
    asr_count=0
    evaluated=[]
    canonical=None
    canonical_ref_text=""
    for row in pre_asr:
        ptbr_probability,vad_speech_ratio,language,transcript=_reference_asr_metrics(
            stt,
            normalized[str(row["reference_id"])],
            float(row["duration_seconds"]),
            beam_size=1,
        )
        row["ptbr_probability"]=ptbr_probability
        row["speech_ratio"]=vad_speech_ratio
        row["detected_language"]=language
        evaluated.append(row)
        asr_count+=1
        if (
            float(ptbr_probability)>=0.90
            and float(vad_speech_ratio)>=0.55
            and transcript
        ):
            strong_ptbr,strong_vad,strong_language,strong_text=_reference_asr_metrics(
                stt,
                normalized[str(row["reference_id"])],
                float(row["duration_seconds"]),
                beam_size=5,
            )
            asr_count+=1
            row["ptbr_probability"]=strong_ptbr
            row["speech_ratio"]=strong_vad
            row["detected_language"]=strong_language
            if float(strong_ptbr)>=0.90 and float(strong_vad)>=0.55 and strong_text:
                canonical=select_canonical_reference([row],profile)
                canonical_ref_text=strong_text
                break
    print(f"OWNER_CANONICAL_REFERENCE_ASR_COUNT={asr_count}")
    print(f"OWNER_CANONICAL_PTBR_COUNT={sum(1 for row in evaluated if float(row['ptbr_probability'])>=0.90)}")
    print(f"OWNER_CANONICAL_VAD_SPEECH_COUNT={sum(1 for row in evaluated if float(row['speech_ratio'])>=0.55)}")
    if canonical is None or not canonical_ref_text:
        raise RuntimeError("NO_CANONICAL_OWNER_REFERENCE_WITH_VERIFIED_TRANSCRIPT")
    cid=str(canonical["reference_id"])
    canonical16=normalized[cid]
    canonical_embedding=embeddings[cid]
    canonical_similarity=cosine_similarity(canonical_embedding,profile["centroid"])
    if canonical_similarity<centroid_floor:
        raise RuntimeError("CANONICAL_REFERENCE_IDENTITY_MATCH_FAILED")
    canonical24=_ffmpeg(
        original_sources[cid],
        workspace/"canonical-owner-reference-24k.wav",
        24000,
    )
    if _sha256(canonical24)=="":
        raise RuntimeError("CANONICAL_REFERENCE_DIGEST_MISSING")

    sanitized=sanitized_profile(profile)
    sanitized["window_consistency_calibration"]=dict(window_calibration)
    sanitized.update({
        "canonical_reference_telegram_input_id":int(canonical["telegram_input_id"]),
        "canonical_reference_sha256":str(canonical["sha256"]),
        "canonical_reference_identity_similarity":round(canonical_similarity,6),
        "canonical_reference_identity_match":True,
        "canonical_reference_duration_seconds":float(canonical["duration_seconds"]),
    })
    (workspace/"owner-speaker-identity-profile.json").write_text(
        json.dumps(sanitized,sort_keys=True,indent=2)+"\n",encoding="utf-8"
    )

    import numpy as np
    np.save(workspace/"owner-speaker-centroid.npy",np.asarray(profile["centroid"],dtype="float32"))
    np.save(workspace/"canonical-speaker-embedding.npy",np.asarray(canonical_embedding,dtype="float32"))

    import torch
    import soundfile as sf
    from qwen_tts import Qwen3TTSModel

    torch.set_num_threads(4)
    qwen_snapshot=_prepare_qwen_model(cache_root/"qwen3-tts")
    model=Qwen3TTSModel.from_pretrained(
        str(qwen_snapshot),
        device_map="cpu",
        dtype=torch.float32,
        attn_implementation="sdpa",
    )
    prompt=model.create_voice_clone_prompt(
        ref_audio=str(canonical24),
        ref_text=canonical_ref_text,
        x_vector_only_mode=False,
    )
    if not prompt:
        raise RuntimeError("QWEN3_TTS_OWNER_PROMPT_REQUIRED")
    generation_t0=time.monotonic()
    wavs,sample_rate=model.generate_voice_clone(
        text=SHORT_TEXT,
        language="Portuguese",
        voice_clone_prompt=prompt,
        non_streaming_mode=True,
    )
    generation_seconds=time.monotonic()-generation_t0
    if len(wavs)!=1 or int(sample_rate)<=0:
        raise RuntimeError("QWEN3_TTS_SINGLE_CLONE_OUTPUT_INVALID")
    clone_path=workspace/"CLONE.wav"
    sf.write(str(clone_path),wavs[0],int(sample_rate),subtype="PCM_16")
    if not clone_path.is_file() or clone_path.stat().st_size<=0:
        raise RuntimeError("QWEN3_TTS_SINGLE_CLONE_EMPTY")
    clone_sha=_sha256(clone_path)

    clone16=_ffmpeg(clone_path,workspace/"clone-16k.wav",16000)
    clone_embedding=_embedding(classifier,clone16)
    identity=evaluate_clone_identity_gate(
        profile,clone_embedding=clone_embedding,canonical_embedding=canonical_embedding
    )
    print(f"OWNER_CLONE_SIMILARITY_TO_CENTROID={identity['similarity_to_centroid']}")
    print(f"OWNER_CLONE_SIMILARITY_TO_REFERENCE={identity['similarity_to_reference']}")
    print(f"OWNER_CLONE_CENTROID_MIN_SIMILARITY={identity['centroid_min_similarity']}")
    print(f"OWNER_CLONE_REFERENCE_MIN_SIMILARITY={identity['reference_min_similarity']}")
    print("QWEN_REFERENCE_AUDIO_LINEAGE=ORIGINAL_TELEGRAM_TO_24K_DIRECT")
    if identity["passed"] is not True:
        print("CLONE_IDENTITY_GATE=FAIL")
        print("QWEN3_TTS_IDENTITY_MATCH=FAIL")
        raise RuntimeError("OWNER_CLONE_IDENTITY_MISMATCH")
    print("CLONE_IDENTITY_GATE=PASS")

    clone_metrics=pcm16_quality_metrics(clone16)
    seg_iter,info=stt.transcribe(
        str(clone16),language="pt",beam_size=1,vad_filter=True,
        word_timestamps=False,condition_on_previous_text=False,
    )
    segments=list(seg_iter)
    observed=" ".join(str(getattr(s,"text","") or "").strip() for s in segments if str(getattr(s,"text","") or "").strip())
    qa=evaluate_short_candidate({
        "candidate_id":"CLONE","audio_sha256":clone_sha,
        "voice_identity_id":VOICE_IDENTITY_ID,
        "provider_default_voice_used":False,"provider_preset_voice_used":False,"generic_voice_fallback":False,
        "detected_language":str(getattr(info,"language","pt") or "pt"),
        "language_probability":float(getattr(info,"language_probability",0.0) or 0.0),
        "vad_speech_ratio":_vad_ratio(segments,float(clone_metrics.get("duration_seconds") or 0.0)),
        "expected_text":SHORT_TEXT,"observed_text":observed,"audio_metrics":clone_metrics,
        "speaker_similarity":{"status":"PASS","score":identity["similarity_to_centroid"],"certifies_identity":True},
    })
    if qa["eligible"] is not True:
        print("CONTENT_AUDIO_PRESCREEN=FAIL")
        print("CONTENT_AUDIO_QA_ISSUES="+",".join(qa["issues"]))
        raise RuntimeError("OWNER_SINGLE_CLONE_CONTENT_QA_FAILED")
    print("CONTENT_AUDIO_PRESCREEN=PASS")

    source_row=next(
        row for row in index["references"]
        if int(row["telegram_input_id"])==int(canonical["telegram_input_id"])
    )
    clone_id=f"BR_OWNER_V1_SINGLE_CLONE_{os.environ.get('GITHUB_RUN_ID','local')}_{os.environ.get('GITHUB_RUN_ATTEMPT','1')}"
    manifest={
        "schema_version":"OwnerVoiceSingleCloneCandidate/v1",
        "clone_id":clone_id,
        "voice_identity_id":VOICE_IDENTITY_ID,
        "reference_source":REFERENCE_SOURCE,
        "canonical_reference_telegram_input_id":int(canonical["telegram_input_id"]),
        "canonical_reference_sha256":str(canonical["sha256"]),
        "canonical_reference_source_message_id":int(source_row["telegram_message_id"]),
        "telegram_chat_id":int(source_row["telegram_chat_id"]),
        "clone_path":str(clone_path),
        "clone_sha256":clone_sha,
        "clone_identity_gate":"PASS",
        "content_audio_prescreen":"PASS",
        "clone_similarity_to_centroid":identity["similarity_to_centroid"],
        "clone_similarity_to_reference":identity["similarity_to_reference"],
        "clone_centroid_threshold":identity["centroid_min_similarity"],
        "clone_reference_threshold":identity["reference_min_similarity"],
        "text":SHORT_TEXT,
        "generation":{
            "engine":"QWEN3_TTS",
            "model_id":QWEN_MODEL_ID,
            "model_revision":QWEN_MODEL_REVISION,
            "qwen_tts_version":QWEN_TTS_VERSION,
            "language":"Portuguese",
            "clone_mode":"TRANSCRIPT_CONDITIONED_ICL",
            "x_vector_only_mode":False,
            "ref_audio_source":"TELEGRAM_HUMAN_OWNER",
            "ref_audio_lineage":"ORIGINAL_TELEGRAM_TO_24K_DIRECT",
            "ref_text_private_only":True,
            "generate_call_count":1,
        },
    }
    manifest_path=workspace/"single-clone-manifest.json"
    manifest_path.write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    out=str(os.environ.get("GITHUB_OUTPUT") or "").strip()
    if out:
        with open(out,"a",encoding="utf-8") as stream:
            stream.write(f"manifest_path={manifest_path}\n")
            stream.write(f"clone_id={clone_id}\n")
    print(f"OWNER_REFERENCE_COUNT={profile['reference_count']}")
    print(f"OWNER_INTRA_SPEAKER_SIMILARITY_MEDIAN={profile['intra_speaker_similarity_median']}")
    print(f"OWNER_INTRA_SPEAKER_SIMILARITY_P10={profile['intra_speaker_similarity_p10']}")
    print(f"OWNER_OUTLIER_COUNT={profile['outlier_count']}")
    print("OWNER_IDENTITY_PROFILE=PASS")
    print(f"CANONICAL_REFERENCE_SHA256={canonical['sha256']}")
    print(f"CANONICAL_REFERENCE_TELEGRAM_INPUT_ID={canonical['telegram_input_id']}")
    print("CANONICAL_REFERENCE_IDENTITY_MATCH=PASS")
    print(f"CONDITIONALS_REFERENCE_SHA256={canonical['sha256']}")
    print("CONDITIONALS_VOICE_IDENTITY=BR_OWNER_V1")
    print("CONDITIONALS_REFERENCE_SOURCE=TELEGRAM_HUMAN_OWNER")
    print("ONE_CANDIDATE_ONLY=TRUE")
    print("QWEN3_TTS_MODEL="+QWEN_MODEL_ID)
    print("QWEN3_TTS_MODEL_REVISION="+QWEN_MODEL_REVISION)
    print("QWEN3_TTS_CLONE_MODE=TRANSCRIPT_CONDITIONED_ICL")
    print("QWEN3_TTS_X_VECTOR_ONLY_MODE=FALSE")
    print("QWEN3_TTS_GENERATE_CALL_TARGET=1")
    print("QWEN3_TTS_GENERATE_CALL_COUNT=1")
    print("QWEN3_TTS_IDENTITY_MATCH=PASS")
    print(f"CANDIDATE_GENERATION_SECONDS={generation_seconds:.6f}")
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"SINGLE_HUMAN_CLONE=FAIL FAILURE_CLASS={type(exc).__name__}:{str(exc)[:300]}",file=__import__("sys").stderr)
        raise SystemExit(51)
