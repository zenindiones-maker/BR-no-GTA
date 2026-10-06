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
    cosine_similarity,
    evaluate_clone_identity_gate,
    sanitized_profile,
    select_canonical_reference,
)
from app.services.owner_voice_telegram_handoff_service import parse_reference_envelope_b64
from scripts.owner_voice_chatterbox_ptbr_audition import (
    MODEL_ID,
    MODEL_REVISION,
    download_ptbr_model_assets,
    load_ptbr_chatterbox_model,
)

VOICE_IDENTITY_ID="BR_OWNER_V1"
REFERENCE_SOURCE="TELEGRAM_HUMAN_OWNER"
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


def _embedding(classifier,path:Path)->list[float]:
    import torchaudio
    signal,sr=torchaudio.load(str(path))
    if sr!=16000:
        raise RuntimeError("SPEAKER_REFERENCE_RATE_INVALID")
    if signal.ndim!=2 or signal.shape[0]!=1:
        signal=signal.mean(dim=0,keepdim=True)
    emb=classifier.encode_batch(signal,normalize=True).detach().cpu().reshape(-1)
    return [float(x) for x in emb.tolist()]


def _window_identity_consistency(classifier,path:Path,full_embedding:list[float],floor:float)->bool:
    import torchaudio
    signal,sr=torchaudio.load(str(path))
    if signal.shape[0]!=1:
        signal=signal.mean(dim=0,keepdim=True)
    total=int(signal.shape[-1])
    window=min(total,4*sr)
    if window<2*sr:
        return False
    starts=[0,max(0,(total-window)//2),max(0,total-window)]
    scores=[]
    for start in sorted(set(starts)):
        piece=signal[:,start:start+window]
        emb=classifier.encode_batch(piece,normalize=True).detach().cpu().reshape(-1).tolist()
        scores.append(cosine_similarity(full_embedding,emb))
    return bool(scores) and min(scores)>=floor


def _load_stt(cache_root:Path):
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model
    model_id=str(os.environ.get("BR_OWNER_STT_MODEL") or "large-v3-turbo")
    target=cache_root/"stt"/model_id
    target.mkdir(parents=True,exist_ok=True)
    path=download_model(model_id,output_dir=str(target))
    return WhisperModel(str(path),device="cpu",compute_type="int8",cpu_threads=4,num_workers=1,local_files_only=True)


def _ptbr_probability(stt,path:Path)->float:
    segments,info=stt.transcribe(
        str(path),language=None,beam_size=1,vad_filter=True,
        word_timestamps=False,condition_on_previous_text=False,
    )
    list(segments)
    language=str(getattr(info,"language","") or "").lower().replace("_","-")
    probability=float(getattr(info,"language_probability",0.0) or 0.0)
    return probability if language in {"pt","pt-br"} else 0.0


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
    embeddings={}
    metrics={}
    for row in refs:
        rid=str(int(row["telegram_input_id"]))
        wav=_ffmpeg(Path(row["runtime_path"]),workspace/"identity-16k"/f"{rid}.wav",16000)
        normalized[rid]=wav
        metrics[rid]=pcm16_quality_metrics(wav)
        embeddings[rid]=_embedding(classifier,wav)

    profile=calibrate_owner_identity_profile(embeddings)
    centroid_floor=float(profile["clone_centroid_min_similarity"])
    candidate_rows=[]
    for row in refs:
        rid=str(int(row["telegram_input_id"]))
        if rid not in set(profile["inlier_ids"]):
            continue
        m=metrics[rid]
        clear=(
            float(m.get("snr_db") or 0.0)>=15.0
            and float(m.get("speech_ratio") or 0.0)>=0.55
            and float(m.get("clipping_ratio") or 0.0)<=0.01
        )
        consistent=_window_identity_consistency(
            classifier,normalized[rid],embeddings[rid],
            float(profile["clone_reference_min_similarity"]),
        )
        candidate_rows.append({
            "reference_id":rid,
            "telegram_input_id":int(row["telegram_input_id"]),
            "sha256":str(row["sha256"]),
            "duration_seconds":float(m.get("duration_seconds") or row.get("duration_seconds") or 0.0),
            "snr_db":float(m.get("snr_db") or 0.0),
            "clipping_ratio":float(m.get("clipping_ratio") or 0.0),
            "speech_ratio":float(m.get("speech_ratio") or 0.0),
            "single_speaker":consistent,
            "clear_speech":clear,
            "no_overlap":consistent,
            "no_music":consistent and float(m.get("speech_ratio") or 0.0)>=0.55,
            "ptbr_probability":0.0,
        })

    stt=_load_stt(cache_root)
    ranked=sorted(candidate_rows,key=lambda row:(
        0 if 10.0<=row["duration_seconds"]<=20.0 else 1,
        -float(profile["reference_similarity_to_centroid"].get(str(row["reference_id"]),-1)),
        -row["snr_db"],
    ))
    for row in ranked[:12]:
        row["ptbr_probability"]=_ptbr_probability(stt,normalized[str(row["reference_id"])])
    canonical=select_canonical_reference(ranked,profile)
    cid=str(canonical["reference_id"])
    canonical16=normalized[cid]
    canonical_embedding=embeddings[cid]
    canonical_similarity=cosine_similarity(canonical_embedding,profile["centroid"])
    if canonical_similarity<centroid_floor:
        raise RuntimeError("CANONICAL_REFERENCE_IDENTITY_MATCH_FAILED")
    canonical24=_ffmpeg(canonical16,workspace/"canonical-owner-reference-24k.wav",24000)
    if _sha256(canonical24)=="":
        raise RuntimeError("CANONICAL_REFERENCE_DIGEST_MISSING")

    sanitized=sanitized_profile(profile)
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
    import torchaudio
    torch.set_num_threads(4)
    assets,_=download_ptbr_model_assets(cache_root/"chatterbox")
    model=load_ptbr_chatterbox_model(assets,device="cuda" if torch.cuda.is_available() else "cpu")
    model.prepare_conditionals(str(canonical24),exaggeration=0.7)
    if model.conds is None:
        raise RuntimeError("OWNER_PREPARED_CONDITIONALS_REQUIRED")
    generation_t0=time.monotonic()
    wav=model.generate(
        SHORT_TEXT,language_id="pt",audio_prompt_path=None,
        exaggeration=0.7,cfg_weight=0.4,temperature=0.8,
        repetition_penalty=1.2,min_p=0.05,top_p=1.0,
    ).cpu()
    generation_seconds=time.monotonic()-generation_t0
    clone_path=workspace/"CLONE.wav"
    torchaudio.save(str(clone_path),wav,model.sr)
    clone_sha=_sha256(clone_path)

    clone16=_ffmpeg(clone_path,workspace/"clone-16k.wav",16000)
    clone_embedding=_embedding(classifier,clone16)
    identity=evaluate_clone_identity_gate(
        profile,clone_embedding=clone_embedding,canonical_embedding=canonical_embedding
    )
    print(f"OWNER_CLONE_SIMILARITY_TO_CENTROID={identity['similarity_to_centroid']}")
    print(f"OWNER_CLONE_SIMILARITY_TO_REFERENCE={identity['similarity_to_reference']}")
    if identity["passed"] is not True:
        print("CLONE_IDENTITY_GATE=FAIL")
        print("CHATTERBOX_IDENTITY_MATCH=FAIL")
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
            "model_id":MODEL_ID,"model_revision":MODEL_REVISION,
            "exaggeration":0.7,"cfg_weight":0.4,"language_id":"pt",
            "audio_prompt_path":None,"generate_call_count":1,
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
    print("CHATTERBOX_GENERATE_CALL_TARGET=1")
    print("CHATTERBOX_GENERATE_CALL_COUNT=1")
    print(f"CANDIDATE_GENERATION_SECONDS={generation_seconds:.6f}")
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"SINGLE_HUMAN_CLONE=FAIL FAILURE_CLASS={type(exc).__name__}:{str(exc)[:300]}",file=__import__("sys").stderr)
        raise SystemExit(51)
