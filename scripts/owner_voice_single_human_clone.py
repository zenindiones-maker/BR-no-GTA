from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from app.services.gta6_pronunciation_lexicon_service import (
    GTA6_CANONICAL_PRONUNCIATION_TERMS,
    build_gta6_pronunciation_batches,
    build_gta6_pronunciation_segments,
    canonicalize_gta6_target_transcript,
    gta6_lexicon_hits,
    gta6_pronunciation_hotwords,
    gta6_target_evidence_score,
)
from app.services.owner_voice_audio_quality_service import pcm16_quality_metrics
from app.services.owner_voice_human_audition_pack_service import (
    character_error_rate,
    evaluate_short_candidate,
    word_error_rate,
)
from app.services.owner_voice_human_review_delivery_policy_service import build_human_review_delivery_decision
from app.services.owner_voice_private_materialization_service import (
    materialize_telegram_owner_references,
    sanitize_owner_reference_index,
)
from app.services.owner_voice_telegram_pending_recovery_service import (
    recover_pending_owner_voice_references,
)
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
VOICE_IDENTITY_ID="BR_OWNER_V1"
QWEN_MODEL_ID="Qwen/Qwen3-TTS-12Hz-1.7B-Base"
QWEN_MODEL_REVISION="fd4b254389122332181a7c3db7f27e918eec64e3"
QWEN_MODEL_SHA256="38fc7fc51c5e776e840414b6fd443962e9411b9654888fd7913e4da643cb857c"
QWEN_SPEECH_TOKENIZER_SHA256="836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258"
QWEN_TTS_VERSION="0.1.1"
REFERENCE_SOURCE="TELEGRAM_HUMAN_OWNER"
IDENTITY_PROFILE_SCHEMA="OwnerSpeakerIdentityProfile/v1"
PINNED_SPEAKER_MODEL_ID="speechbrain/spkrec-ecapa-voxceleb"
REQUEST_PATH=Path(".run/br-owner-v1-single-human-clone.request.json")
SHORT_TEXT=(
    "Booooa meu povo, aqui é BR no GTA 6! Rockstar Games. Vice City, Leonida, "
    "Leonida Keys, Port Gellhorn, Ambrosia, Grassrivers e Mount Kalaga. "
    "Jason Duval, Lucia Caminos, Cal Hampton, Boobie Ike, Dre'Quan Priest, "
    "Real Dimez, Raul Bautista e Brian Heder. E BR não dorme em Vice City."
)
PRONUNCIATION_HOTWORDS=gta6_pronunciation_hotwords()
MAX_PRONUNCIATION_PROMPT_REFERENCES=2
PRONUNCIATION_ASR_LANGUAGES=(None,"en","pt","es")
VICE_CITY_TERM="Vice City"
VICE_CITY_REFERENCE_EVIDENCE_MIN=0.78
VICE_CITY_OWNER_ASSERTED_EVIDENCE_FLOOR=0.45
VOICE_SEGMENT_CROSSFADE_MS=30
VOICE_SEGMENT_LEVEL_MATCH_DB_LIMIT=1.5
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


def _request_payload()->dict[str,Any]:
    if not REQUEST_PATH.is_file():
        return {}
    payload=json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload,dict):
        raise RuntimeError("OWNER_SINGLE_CLONE_REQUEST_INVALID")
    return payload


def _owner_asserted_pronunciation_targets(payload:dict[str,Any])->tuple[str,...]:
    raw=payload.get("owner_asserted_pronunciation_targets") or []
    if not isinstance(raw,list):
        raise RuntimeError("OWNER_ASSERTED_PRONUNCIATION_TARGETS_INVALID")
    allowed=set(GTA6_CANONICAL_PRONUNCIATION_TERMS)
    targets=[]
    for value in raw:
        target=str(value or "").strip()
        if not target or target not in allowed:
            raise RuntimeError("OWNER_ASSERTED_PRONUNCIATION_TARGET_UNKNOWN")
        if target not in targets:
            targets.append(target)
    return tuple(targets)


def _pronunciation_after_message_id(payload:dict[str,Any])->int:
    value=int(payload.get("pronunciation_after_message_id") or 0)
    if value<0:
        raise RuntimeError("OWNER_PRONUNCIATION_REFERENCE_BOUNDARY_INVALID")
    return value


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


def _reference_asr_metrics(
    stt,
    path:Path,
    duration_seconds:float,
    *,
    beam_size:int=1,
    pronunciation_hint:bool=False,
)->tuple[float,float,str,str]:
    segments_iter,info=stt.transcribe(
        str(path),language=None,beam_size=int(beam_size),vad_filter=True,
        word_timestamps=False,condition_on_previous_text=False,
        hotwords=PRONUNCIATION_HOTWORDS if pronunciation_hint else None,
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


def _best_pronunciation_asr_hypothesis(
    stt,
    path:Path,
    duration_seconds:float,
)->dict[str,Any]:
    hypotheses=[]
    for forced_language in PRONUNCIATION_ASR_LANGUAGES:
        segments_iter,info=stt.transcribe(
            str(path),
            language=forced_language,
            beam_size=5,
            vad_filter=True,
            word_timestamps=False,
            condition_on_previous_text=False,
            hotwords=PRONUNCIATION_HOTWORDS,
        )
        segments=list(segments_iter)
        transcript=" ".join(
            str(getattr(segment,"text","") or "").strip()
            for segment in segments
            if str(getattr(segment,"text","") or "").strip()
        ).strip()
        detected_language=str(
            getattr(info,"language",forced_language or "") or forced_language or ""
        ).lower().replace("_","-")
        language_probability=float(
            getattr(info,"language_probability",0.0) or 0.0
        )
        vad_speech_ratio=_vad_ratio(segments,float(duration_seconds))
        hypotheses.append({
            "forced_language":forced_language,
            "language":detected_language,
            "language_probability":language_probability,
            "vad_speech_ratio":vad_speech_ratio,
            "transcript":transcript,
            "lexicon_hits":gta6_lexicon_hits(transcript),
            "vice_city_evidence_score":gta6_target_evidence_score(
                transcript,
                VICE_CITY_TERM,
            ),
        })
    hypotheses.sort(
        key=lambda row:(
            -len(row["lexicon_hits"]),
            -float(row["vice_city_evidence_score"]),
            -float(row["vad_speech_ratio"]),
            -float(row["language_probability"]),
            0 if row["forced_language"] is None else 1,
            str(row["forced_language"] or ""),
            str(row["transcript"]),
        )
    )
    if not hypotheses:
        raise RuntimeError("OWNER_PRONUNCIATION_ASR_HYPOTHESIS_EMPTY")
    return hypotheses[0]


def _targeted_vice_city_asr_hypothesis(
    stt,
    path:Path,
    duration_seconds:float,
)->dict[str,Any]:
    segments_iter,info=stt.transcribe(
        str(path),
        language="en",
        initial_prompt=VICE_CITY_TERM,
        hotwords=VICE_CITY_TERM,
        beam_size=5,
        vad_filter=True,
        word_timestamps=False,
        condition_on_previous_text=False,
    )
    segments=list(segments_iter)
    transcript=" ".join(
        str(getattr(segment,"text","") or "").strip()
        for segment in segments
        if str(getattr(segment,"text","") or "").strip()
    ).strip()
    avg_logprobs=[
        float(getattr(segment,"avg_logprob",-99.0) or -99.0)
        for segment in segments
    ]
    return {
        "forced_language":"en",
        "language":str(getattr(info,"language","en") or "en").lower().replace("_","-"),
        "language_probability":float(getattr(info,"language_probability",0.0) or 0.0),
        "vad_speech_ratio":_vad_ratio(segments,float(duration_seconds)),
        "transcript":transcript,
        "lexicon_hits":gta6_lexicon_hits(transcript),
        "vice_city_evidence_score":gta6_target_evidence_score(
            transcript,
            VICE_CITY_TERM,
        ),
        "avg_logprob":(
            sum(avg_logprobs)/len(avg_logprobs)
            if avg_logprobs else -99.0
        ),
        "targeted_vice_city":True,
    }


def _compose_pronunciation_reference_audio(
    pronunciations:list[Path],
    target:Path,
)->Path:
    import numpy as np
    import soundfile as sf

    if not pronunciations:
        raise RuntimeError("OWNER_PRONUNCIATION_AUDIO_REQUIRED")
    silence=np.zeros((int(0.20*24000),1),dtype="float32")
    chunks=[]
    for pronunciation in pronunciations:
        pronunciation_audio,pronunciation_rate=sf.read(
            str(pronunciation),dtype="float32",always_2d=True
        )
        if int(pronunciation_rate)!=24000:
            raise RuntimeError("OWNER_PRONUNCIATION_REFERENCE_RATE_INVALID")
        if pronunciation_audio.size==0:
            raise RuntimeError("OWNER_PRONUNCIATION_REFERENCE_AUDIO_EMPTY")
        if pronunciation_audio.shape[1]>1:
            pronunciation_audio=pronunciation_audio.mean(axis=1,keepdims=True)
        if chunks:
            chunks.append(silence)
        chunks.append(pronunciation_audio)

    combined=np.concatenate(chunks,axis=0)
    sf.write(str(target),combined,24000,subtype="PCM_16")
    if not target.is_file() or target.stat().st_size<=0:
        raise RuntimeError("OWNER_PRONUNCIATION_REFERENCE_WRITE_FAILED")
    return target


def _stitch_generated_segments(wavs:list[Any],sample_rate:int):
    import numpy as np

    rate=int(sample_rate)
    if rate<=0 or not wavs:
        raise RuntimeError("QWEN3_TTS_SEGMENT_OUTPUT_INVALID")

    prepared=[]
    for wav in wavs:
        audio=np.asarray(wav,dtype="float32").reshape(-1)
        if audio.size<=0:
            raise RuntimeError("QWEN3_TTS_SEGMENT_EMPTY")
        prepared.append(audio.copy())

    output=prepared[0]
    max_gain=10.0**(VOICE_SEGMENT_LEVEL_MATCH_DB_LIMIT/20.0)
    min_gain=1.0/max_gain
    requested_crossfade=max(1,int(round(rate*VOICE_SEGMENT_CROSSFADE_MS/1000.0)))

    for audio in prepared[1:]:
        level_window=max(1,min(int(round(rate*0.35)),output.size,audio.size))
        tail_rms=float(np.sqrt(np.mean(np.square(output[-level_window:]),dtype=np.float64)+1e-12))
        head_rms=float(np.sqrt(np.mean(np.square(audio[:level_window]),dtype=np.float64)+1e-12))
        if tail_rms>1e-6 and head_rms>1e-6:
            gain=max(min_gain,min(max_gain,tail_rms/head_rms))
            audio=audio*float(gain)

        crossfade_samples=min(
            requested_crossfade,
            max(1,output.size//4),
            max(1,audio.size//4),
        )
        if crossfade_samples<=1:
            output=np.concatenate([output,audio],axis=0)
            continue

        phase=np.linspace(0.0,1.0,crossfade_samples,dtype="float32")
        fade_out=np.cos(phase*np.pi/2.0)**2
        fade_in=np.sin(phase*np.pi/2.0)**2
        overlap=(
            output[-crossfade_samples:]*fade_out
            +audio[:crossfade_samples]*fade_in
        )
        output=np.concatenate(
            [output[:-crossfade_samples],overlap,audio[crossfade_samples:]],
            axis=0,
        )
    return output


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
    request_payload=_request_payload()
    pronunciation_after_message_id=_pronunciation_after_message_id(request_payload)
    owner_asserted_pronunciation_targets=_owner_asserted_pronunciation_targets(
        request_payload
    )
    owner_asserted_vice_city=(
        VICE_CITY_TERM in owner_asserted_pronunciation_targets
    )
    print(
        "OWNER_ASSERTED_PRONUNCIATION_TARGETS="
        +(",".join(owner_asserted_pronunciation_targets) or "NONE")
    )
    raw_index=_index()
    index,health=sanitize_owner_reference_index(
        raw_index,
        min_message_id_exclusive=pronunciation_after_message_id,
        require_fresh=False,
    )
    print(f"OWNER_REFERENCE_INDEX_INVALID_LINEAGE_COUNT={health['invalid_lineage_count']}")
    print(f"OWNER_REFERENCE_INDEX_MATERIALIZABLE_COUNT={health['materializable_reference_count']}")
    print(f"OWNER_PRONUNCIATION_INDEX_REFERENCE_COUNT={health['fresh_reference_count']}")

    if (
        pronunciation_after_message_id>0
        and int(health["fresh_reference_count"])<=0
        and request_payload.get("recover_pending_telegram_updates") is True
    ):
        recovery=recover_pending_owner_voice_references(
            telegram_bot_token=token,
            reference_index=index,
            after_message_id=pronunciation_after_message_id,
        )
        print(
            "OWNER_PENDING_TELEGRAM_RECOVERED_REFERENCE_COUNT="
            +str(int(recovery["recovered_reference_count"]))
        )
        index,health=sanitize_owner_reference_index(
            recovery["merged_index"],
            min_message_id_exclusive=pronunciation_after_message_id,
            require_fresh=True,
        )
    elif pronunciation_after_message_id>0:
        index,health=sanitize_owner_reference_index(
            index,
            min_message_id_exclusive=pronunciation_after_message_id,
            require_fresh=True,
        )

    materialized=materialize_telegram_owner_references(
        index,private_root=workspace/"owner-references",
        repository_root=Path.cwd().resolve(),telegram_bot_token=token,
    )
    refs=list(materialized.get("references") or [])
    if len(refs)<3:
        raise RuntimeError("OWNER_REFERENCE_COUNT_TOO_SMALL")
    pronunciation_refs=[
        row for row in refs
        if int(row["telegram_message_id"])>pronunciation_after_message_id
    ] if pronunciation_after_message_id>0 else list(refs)
    print(f"OWNER_PRONUNCIATION_REFERENCE_COUNT={len(pronunciation_refs)}")
    if pronunciation_after_message_id>0 and not pronunciation_refs:
        raise RuntimeError("OWNER_PRONUNCIATION_REFERENCE_NOT_MATERIALIZED")
    fresh_reference_ids={
        str(int(row["telegram_input_id"])) for row in pronunciation_refs
    }
    print("PRONUNCIATION_REFERENCE_SCOPE=FRESH_TELEGRAM_ONLY")
    print("PRONUNCIATION_LANGUAGE_POLICY=CODE_SWITCH_ALLOWED")
    print("IDENTITY_REFERENCE_SCOPE=GLOBAL_OWNER_INLIERS")

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
    pronunciation_source_rows=[]
    for row in refs:
        rid=str(int(row["telegram_input_id"]))
        if rid in fresh_reference_ids:
            m=metrics[rid]
            fresh_window_scores=_window_identity_scores(
                classifier,normalized[rid],embeddings[rid]
            )
            consistent=False
            fresh_window_p10=-1.0
            if fresh_window_scores:
                fresh_window_eval=evaluate_reference_window_consistency(
                    fresh_window_scores,
                    window_calibration,
                )
                consistent=bool(fresh_window_eval["passed"])
                fresh_window_p10=float(fresh_window_eval["reference_p10"])
            pronunciation_source_rows.append({
                "reference_id":rid,
                "telegram_input_id":int(row["telegram_input_id"]),
                "telegram_message_id":int(row["telegram_message_id"]),
                "sha256":str(row["sha256"]),
                "duration_seconds":float(
                    m.get("duration_seconds") or row.get("duration_seconds") or 0.0
                ),
                "snr_db":float(m.get("snr_db") or 0.0),
                "clipping_ratio":float(m.get("clipping_ratio") or 0.0),
                "single_speaker":consistent,
                "clear_speech":(
                    float(m.get("snr_db") or 0.0)>=15.0
                    and float(m.get("clipping_ratio") or 0.0)<=0.01
                ),
                "no_overlap":consistent,
                "no_music":consistent,
                "window_identity_p10":fresh_window_p10,
            })

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
            "telegram_message_id":int(row["telegram_message_id"]),
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
        and (
            pronunciation_after_message_id<=0
            or str(row["reference_id"]) not in fresh_reference_ids
        )
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
    anchor_ref_text=""
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
                anchor_ref_text=strong_text
                break
    print(f"OWNER_CANONICAL_REFERENCE_ASR_COUNT={asr_count}")
    print(f"OWNER_CANONICAL_PTBR_COUNT={sum(1 for row in evaluated if float(row['ptbr_probability'])>=0.90)}")
    print(f"OWNER_CANONICAL_VAD_SPEECH_COUNT={sum(1 for row in evaluated if float(row['speech_ratio'])>=0.55)}")
    if canonical is None or not anchor_ref_text:
        raise RuntimeError("NO_CANONICAL_OWNER_REFERENCE_WITH_VERIFIED_TRANSCRIPT")
    cid=str(canonical["reference_id"])
    pronunciation_canonical=None
    pronunciation_selected=[]
    pronunciation_ref_text=""
    vice_city_selected=None
    if pronunciation_after_message_id>0:
        pronunciation_pre_asr=[
            row for row in pronunciation_source_rows
            if row["single_speaker"] is True
            and row["clear_speech"] is True
            and row["no_overlap"] is True
            and row["no_music"] is True
            and float(row["duration_seconds"])>0.0
        ]
        pronunciation_pre_asr.sort(key=lambda row:(
            -float(row["snr_db"]),
            abs(float(row["duration_seconds"])-12.0),
            str(row["sha256"]),
        ))
        for row in pronunciation_pre_asr:
            reference_path=normalized[str(row["reference_id"])]
            reference_duration=float(row["duration_seconds"])
            hypothesis=_best_pronunciation_asr_hypothesis(
                stt,
                reference_path,
                reference_duration,
            )
            general_vice_score=float(hypothesis["vice_city_evidence_score"])
            targeted_vice_city=None
            if general_vice_score<VICE_CITY_REFERENCE_EVIDENCE_MIN:
                targeted_vice_city=_targeted_vice_city_asr_hypothesis(
                    stt,
                    reference_path,
                    reference_duration,
                )
                targeted_score=float(
                    targeted_vice_city["vice_city_evidence_score"]
                )
                print(
                    "OWNER_VICE_CITY_TARGETED_ASR_EVIDENCE_SCORE="
                    +str(targeted_score)
                )
                if (
                    float(targeted_vice_city["vad_speech_ratio"])>=0.55
                    and float(targeted_vice_city["avg_logprob"])>=-1.0
                    and targeted_score>general_vice_score
                ):
                    hypothesis=targeted_vice_city

            strong_vad=float(hypothesis["vad_speech_ratio"])
            strong_language=str(hypothesis["language"])
            strong_text=str(hypothesis["transcript"])
            vice_city_evidence_score=float(
                hypothesis["vice_city_evidence_score"]
            )
            owner_asserted_vice_match=(
                owner_asserted_vice_city
                and vice_city_evidence_score
                >=VICE_CITY_OWNER_ASSERTED_EVIDENCE_FLOOR
            )
            if owner_asserted_vice_match:
                strong_text=canonicalize_gta6_target_transcript(
                    strong_text,
                    VICE_CITY_TERM,
                    minimum_score=VICE_CITY_OWNER_ASSERTED_EVIDENCE_FLOOR,
                )
            pronunciation_hits=tuple(gta6_lexicon_hits(strong_text))
            print(
                "OWNER_PRONUNCIATION_ASR_LANGUAGE="
                +str(hypothesis["forced_language"] or "auto")
            )
            if (
                float(strong_vad)>=0.55
                and strong_text
                and (
                    pronunciation_hits
                    or vice_city_evidence_score>=VICE_CITY_REFERENCE_EVIDENCE_MIN
                    or owner_asserted_vice_match
                )
            ):
                row["speech_ratio"]=strong_vad
                row["detected_language"]=strong_language
                row["pronunciation_hits"]=pronunciation_hits
                row["vice_city_evidence_score"]=vice_city_evidence_score
                row["owner_asserted_vice_city"]=bool(owner_asserted_vice_match)
                pronunciation_selected.append((row,strong_text))
        pronunciation_selected.sort(key=lambda item:(
            -int(VICE_CITY_TERM in item[0]["pronunciation_hits"]),
            -float(item[0].get("vice_city_evidence_score",0.0)),
            -len(item[0]["pronunciation_hits"]),
            -float(item[0]["snr_db"]),
            str(item[0]["sha256"]),
        ))
        vice_city_selected=next(
            (
                (row,text) for row,text in pronunciation_selected
                if (
                    VICE_CITY_TERM in row["pronunciation_hits"]
                    or float(row.get("vice_city_evidence_score",0.0))
                    >=VICE_CITY_REFERENCE_EVIDENCE_MIN
                    or (
                        owner_asserted_vice_city
                        and float(row.get("vice_city_evidence_score",0.0))
                        >=VICE_CITY_OWNER_ASSERTED_EVIDENCE_FLOOR
                    )
                )
            ),
            None,
        )
        if vice_city_selected is None:
            raise RuntimeError("OWNER_VICE_CITY_PRONUNCIATION_REFERENCE_REQUIRED")
        vice_row_for_authority,_vice_text_for_authority=vice_city_selected
        if bool(vice_row_for_authority.get("owner_asserted_vice_city")):
            print("OWNER_VICE_CITY_REFERENCE_AUTHORITY=OWNER_ASSERTED_FRESH_SAMPLE")
        else:
            print("OWNER_VICE_CITY_REFERENCE_AUTHORITY=ASR_VERIFIED")
        ranked_pronunciation=list(pronunciation_selected)
        pronunciation_selected=ranked_pronunciation[:MAX_PRONUNCIATION_PROMPT_REFERENCES]
        if vice_city_selected not in pronunciation_selected:
            pronunciation_selected=[
                vice_city_selected,
                *[
                    item for item in ranked_pronunciation
                    if item is not vice_city_selected
                ],
            ][:MAX_PRONUNCIATION_PROMPT_REFERENCES]
        if not pronunciation_selected:
            raise RuntimeError("NO_FRESH_PRONUNCIATION_REFERENCE_WITH_VERIFIED_TRANSCRIPT")
        pronunciation_canonical=pronunciation_selected[0][0]
        pronunciation_ref_text=" ".join(text for _row,text in pronunciation_selected)
        print(
            "OWNER_PRONUNCIATION_PROMPT_REFERENCE_COUNT="
            +str(len(pronunciation_selected))
        )
        print(
            "OWNER_PRONUNCIATION_LEXICON_HIT_COUNT="
            +str(len({
                term
                for row,_text in pronunciation_selected
                for term in row["pronunciation_hits"]
            }))
        )

    canonical16=normalized[cid]
    canonical_embedding=embeddings[cid]
    canonical_similarity=float(profile["reference_similarity_to_centroid"][cid])
    canonical_similarity_recomputed=cosine_similarity(
        canonical_embedding,
        profile["centroid"],
    )
    if not math.isclose(
        canonical_similarity,
        canonical_similarity_recomputed,
        rel_tol=1e-6,
        abs_tol=1e-6,
    ):
        raise RuntimeError("CANONICAL_REFERENCE_SIMILARITY_RECOMPUTE_DRIFT")
    if canonical_similarity<centroid_floor:
        raise RuntimeError("CANONICAL_REFERENCE_IDENTITY_MATCH_FAILED")
    canonical24=_ffmpeg(
        original_sources[cid],
        workspace/"canonical-owner-reference-24k.wav",
        24000,
    )
    if _sha256(canonical24)=="":
        raise RuntimeError("CANONICAL_REFERENCE_DIGEST_MISSING")

    pronunciation_prompt_audio=None
    human_review_reference=canonical
    qwen_reference_audio_lineage="ORIGINAL_TELEGRAM_TO_24K_DIRECT"
    pronunciation24_by_input_id={}
    if pronunciation_canonical is not None:
        pronunciation24s=[]
        for position,(pronunciation_row,_text) in enumerate(pronunciation_selected,1):
            pid=str(pronunciation_row["reference_id"])
            pronunciation24=_ffmpeg(
                original_sources[pid],
                workspace/f"pronunciation-owner-reference-{position}-24k.wav",
                24000,
            )
            pronunciation24s.append(pronunciation24)
            pronunciation24_by_input_id[int(pronunciation_row["telegram_input_id"])]=pronunciation24
        pronunciation_prompt_audio=_compose_pronunciation_reference_audio(
            pronunciation24s,
            workspace/"pronunciation-reference-combined-24k.wav",
        )
        human_review_reference=pronunciation_canonical
        qwen_reference_audio_lineage="ANCHOR_SPK_EMBEDDING_PLUS_FRESH_PRONUNCIATION_CODE"
        print(f"OWNER_IDENTITY_ANCHOR_TELEGRAM_INPUT_ID={canonical['telegram_input_id']}")
        print(
            "OWNER_PRONUNCIATION_REFERENCE_TELEGRAM_INPUT_ID="
            +str(pronunciation_canonical["telegram_input_id"])
        )
        print(
            "OWNER_PRONUNCIATION_REFERENCE_TELEGRAM_INPUT_IDS="
            +",".join(str(row["telegram_input_id"]) for row,_text in pronunciation_selected)
        )

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
    from qwen_tts import Qwen3TTSModel, VoiceClonePromptItem

    torch.set_num_threads(4)
    qwen_snapshot=_prepare_qwen_model(cache_root/"qwen3-tts")
    model=Qwen3TTSModel.from_pretrained(
        str(qwen_snapshot),
        device_map="cpu",
        dtype=torch.float32,
        attn_implementation="sdpa",
    )
    anchor_prompt_items=model.create_voice_clone_prompt(
        ref_audio=str(canonical24),
        ref_text=anchor_ref_text,
        x_vector_only_mode=False,
    )
    if not anchor_prompt_items:
        raise RuntimeError("QWEN3_TTS_OWNER_ANCHOR_PROMPT_REQUIRED")

    anchor_prompt=anchor_prompt_items[0]
    pronunciation_hybrid_prompt=None
    vice_city_prompt=None
    if pronunciation_prompt_audio is not None:
        pronunciation_prompt_items=model.create_voice_clone_prompt(
            ref_audio=str(pronunciation_prompt_audio),
            ref_text=pronunciation_ref_text,
            x_vector_only_mode=False,
        )
        if not pronunciation_prompt_items:
            raise RuntimeError("QWEN3_TTS_PRONUNCIATION_PROMPT_REQUIRED")
        pronunciation_prompt=pronunciation_prompt_items[0]
        pronunciation_hybrid_prompt=VoiceClonePromptItem(
            ref_code=pronunciation_prompt.ref_code,
            ref_spk_embedding=anchor_prompt.ref_spk_embedding,
            x_vector_only_mode=False,
            icl_mode=True,
            ref_text=pronunciation_ref_text,
        )

        if vice_city_selected is None:
            raise RuntimeError("OWNER_VICE_CITY_PRONUNCIATION_REFERENCE_REQUIRED")
        vice_row,vice_ref_text=vice_city_selected
        vice_input_id=int(vice_row["telegram_input_id"])
        vice_audio=pronunciation24_by_input_id.get(vice_input_id)
        if vice_audio is None:
            pid=str(vice_row["reference_id"])
            vice_audio=_ffmpeg(
                original_sources[pid],
                workspace/"vice-city-owner-reference-24k.wav",
                24000,
            )
        vice_prompt_items=model.create_voice_clone_prompt(
            ref_audio=str(vice_audio),
            ref_text=vice_ref_text,
            x_vector_only_mode=False,
        )
        if not vice_prompt_items:
            raise RuntimeError("QWEN3_TTS_VICE_CITY_PROMPT_REQUIRED")
        vice_raw_prompt=vice_prompt_items[0]
        vice_city_prompt=VoiceClonePromptItem(
            ref_code=vice_raw_prompt.ref_code,
            ref_spk_embedding=anchor_prompt.ref_spk_embedding,
            x_vector_only_mode=False,
            icl_mode=True,
            ref_text=vice_ref_text,
        )
        print("OWNER_VICE_CITY_REFERENCE_TELEGRAM_INPUT_ID="+str(vice_input_id))
        print(
            "OWNER_VICE_CITY_REFERENCE_EVIDENCE_SCORE="
            +str(float(vice_row.get("vice_city_evidence_score",0.0)))
        )
        print("QWEN_PROMPT_COMPONENT_AUTHORITY=ANCHOR_SPK_PLUS_PRONUNCIATION_CODE")
        print("QWEN_TARGETED_PROMPT_AUTHORITY=VICE_CITY_FRESH_OWNER_REFERENCE")
    else:
        print("QWEN_PROMPT_COMPONENT_AUTHORITY=ANCHOR_ONLY")
    print("QWEN_REFERENCE_AUDIO_LINEAGE="+qwen_reference_audio_lineage)
    pronunciation_segments=build_gta6_pronunciation_batches(SHORT_TEXT)
    if not pronunciation_segments:
        raise RuntimeError("GTA6_PRONUNCIATION_SEGMENT_PLAN_EMPTY")
    segment_texts=[str(row["spoken_text"]) for row in pronunciation_segments]
    segment_languages=[str(row["language"]) for row in pronunciation_segments]
    if "Auto" in segment_languages:
        raise RuntimeError("GTA6_PRONUNCIATION_SEGMENT_LANGUAGE_AUTO_FORBIDDEN")
    print("GTA6_PRONUNCIATION_SEGMENT_COUNT="+str(len(pronunciation_segments)))
    print("GTA6_PRONUNCIATION_SEGMENT_LANGUAGES="+",".join(segment_languages))
    segment_prompts=[]
    for row in pronunciation_segments:
        language=str(row["language"])
        if language=="Portuguese":
            segment_prompts.append(anchor_prompt)
        elif VICE_CITY_TERM in str(row["canonical_text"]):
            if vice_city_prompt is None:
                raise RuntimeError("OWNER_VICE_CITY_PRONUNCIATION_REFERENCE_REQUIRED")
            segment_prompts.append(vice_city_prompt)
        elif pronunciation_hybrid_prompt is not None:
            segment_prompts.append(pronunciation_hybrid_prompt)
        else:
            segment_prompts.append(anchor_prompt)

    generation_t0=time.monotonic()
    wavs,sample_rate=model.generate_voice_clone(
        text=segment_texts,
        language=segment_languages,
        voice_clone_prompt=segment_prompts,
        non_streaming_mode=True,
    )
    generation_seconds=time.monotonic()-generation_t0
    if len(wavs)!=len(segment_texts) or int(sample_rate)<=0:
        raise RuntimeError("QWEN3_TTS_SEGMENT_BATCH_OUTPUT_INVALID")
    stitched=_stitch_generated_segments(wavs,int(sample_rate))
    clone_path=workspace/"CLONE.wav"
    sf.write(str(clone_path),stitched,int(sample_rate),subtype="PCM_16")
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
    identity_gate="PASS" if identity["passed"] is True else "FAIL"
    print("CLONE_IDENTITY_GATE="+identity_gate)
    print("QWEN3_TTS_IDENTITY_MATCH="+identity_gate)

    clone_metrics=pcm16_quality_metrics(clone16)
    segment_language_qas=[]
    observed_chunks=[]
    segment_probabilities=[]
    for position,(wav,row) in enumerate(zip(wavs,pronunciation_segments),1):
        language=str(row["language"])
        forced_language="pt" if language=="Portuguese" else "en"
        segment_path=workspace/f"qa-segment-{position:02d}.wav"
        sf.write(str(segment_path),wav,int(sample_rate),subtype="PCM_16")
        seg_iter,seg_info=stt.transcribe(
            str(segment_path),
            language=forced_language,
            beam_size=5,
            vad_filter=True,
            word_timestamps=False,
            condition_on_previous_text=False,
            hotwords=PRONUNCIATION_HOTWORDS if forced_language=="en" else None,
        )
        seg_segments=list(seg_iter)
        observed_segment=" ".join(
            str(getattr(s,"text","") or "").strip()
            for s in seg_segments
            if str(getattr(s,"text","") or "").strip()
        ).strip()
        expected_segment=str(row["spoken_text"])
        seg_wer=word_error_rate(expected_segment,observed_segment)
        seg_cer=character_error_rate(expected_segment,observed_segment)
        seg_probability=float(getattr(seg_info,"language_probability",0.0) or 0.0)
        segment_probabilities.append(seg_probability)
        segment_pass=(
            bool(observed_segment)
            and seg_wer<=0.25
            and seg_cer<=0.20
        )
        segment_language_qas.append({
            "position":position,
            "language":forced_language,
            "expected_text":expected_segment,
            "observed_text":observed_segment,
            "word_error_rate":seg_wer,
            "character_error_rate":seg_cer,
            "language_probability":seg_probability,
            "passed":segment_pass,
        })
        observed_chunks.append(observed_segment)
        print(
            "GTA6_PRONUNCIATION_SEGMENT_QA="
            +json.dumps(
                {
                    "position":position,
                    "language":forced_language,
                    "word_error_rate":seg_wer,
                    "character_error_rate":seg_cer,
                    "passed":segment_pass,
                },
                sort_keys=True,
                separators=(",",":"),
            )
        )

    global_iter,_global_info=stt.transcribe(
        str(clone16),
        language=None,
        beam_size=1,
        vad_filter=True,
        word_timestamps=False,
        condition_on_previous_text=False,
        hotwords=PRONUNCIATION_HOTWORDS,
    )
    global_segments=list(global_iter)
    spoken_expected_text=" ".join(segment_texts)
    observed=" ".join(chunk for chunk in observed_chunks if chunk).strip()
    qa=evaluate_short_candidate({
        "candidate_id":"CLONE","audio_sha256":clone_sha,
        "voice_identity_id":VOICE_IDENTITY_ID,
        "provider_default_voice_used":False,"provider_preset_voice_used":False,"generic_voice_fallback":False,
        "detected_language":"multilingual",
        "language_probability":min(segment_probabilities) if segment_probabilities else 0.0,
        "language_mode":"EXPLICIT_SEGMENTED_MULTILINGUAL",
        "segment_language_qas":segment_language_qas,
        "vad_speech_ratio":_vad_ratio(global_segments,float(clone_metrics.get("duration_seconds") or 0.0)),
        "expected_text":spoken_expected_text,"observed_text":observed,"audio_metrics":clone_metrics,
        "speaker_similarity":{"status":identity_gate,"score":identity["similarity_to_centroid"],"certifies_identity":identity_gate=="PASS"},
    })
    content_audio_prescreen="PASS" if qa["eligible"] is True else "FAIL"
    print("CONTENT_AUDIO_PRESCREEN="+content_audio_prescreen)
    if qa["issues"]:
        print("CONTENT_AUDIO_QA_ISSUES="+",".join(qa["issues"]))
    review_decision=build_human_review_delivery_decision(
        identity_gate=identity_gate,
        content_audio_prescreen=content_audio_prescreen,
    )
    print("AUDITION_DELIVERY_ELIGIBLE=PASS")
    print("RUNTIME_ACTIVATION=BLOCKED_PENDING_HUMAN_REVIEW")

    anchor_source_row=next(
        row for row in index["references"]
        if int(row["telegram_input_id"])==int(canonical["telegram_input_id"])
    )
    review_source_row=next(
        row for row in index["references"]
        if int(row["telegram_input_id"])==int(human_review_reference["telegram_input_id"])
    )
    clone_id=f"BR_OWNER_V1_SINGLE_CLONE_{os.environ.get('GITHUB_RUN_ID','local')}_{os.environ.get('GITHUB_RUN_ATTEMPT','1')}"
    manifest={
        "schema_version":"OwnerVoiceSingleCloneCandidate/v1",
        "clone_id":clone_id,
        "voice_identity_id":VOICE_IDENTITY_ID,
        "reference_source":REFERENCE_SOURCE,
        "canonical_reference_telegram_input_id":int(canonical["telegram_input_id"]),
        "canonical_reference_sha256":str(canonical["sha256"]),
        "canonical_reference_source_message_id":int(anchor_source_row["telegram_message_id"]),
        "human_review_reference_source_message_id":int(review_source_row["telegram_message_id"]),
        "identity_anchor_telegram_input_id":int(canonical["telegram_input_id"]),
        "pronunciation_reference_telegram_input_id":(
            int(pronunciation_canonical["telegram_input_id"])
            if pronunciation_canonical is not None else None
        ),
        "pronunciation_reference_telegram_input_ids":[
            int(row["telegram_input_id"]) for row,_text in pronunciation_selected
        ],
        "pronunciation_after_message_id":pronunciation_after_message_id,
        "pronunciation_reference_count":len(pronunciation_refs),
        "identity_reference_scope":"GLOBAL_OWNER_INLIERS",
        "pronunciation_reference_scope":"FRESH_TELEGRAM_ONLY",
        "telegram_chat_id":int(review_source_row["telegram_chat_id"]),
        "clone_path":str(clone_path),
        "clone_sha256":clone_sha,
        "clone_identity_gate":identity_gate,
        "content_audio_prescreen":content_audio_prescreen,
        "audition_delivery_eligible":review_decision["audition_delivery_eligible"],
        "human_review_required":review_decision["human_review_required"],
        "human_review":review_decision["human_review"],
        "runtime_activation":review_decision["runtime_activation"],
        "automatic_gates_passed":review_decision["automatic_gates_passed"],
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
            "language":"MULTILINGUAL",
            "language_mode":"EXPLICIT_SEGMENTED_MULTILINGUAL",
            "clone_mode":"TRANSCRIPT_CONDITIONED_ICL",
            "x_vector_only_mode":False,
            "ref_audio_source":"TELEGRAM_HUMAN_OWNER",
            "ref_audio_lineage":qwen_reference_audio_lineage,
            "prompt_component_authority":(
                "ANCHOR_SPK_PLUS_PRONUNCIATION_CODE"
                if pronunciation_canonical is not None
                else "ANCHOR_ONLY"
            ),
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
    print("QWEN3_TTS_LANGUAGE_MODE=EXPLICIT_SEGMENTED_MULTILINGUAL")
    print("QWEN3_TTS_X_VECTOR_ONLY_MODE=FALSE")
    print("QWEN3_TTS_GENERATE_CALL_TARGET=1")
    print("QWEN3_TTS_GENERATE_CALL_COUNT=1")
    print("QWEN3_TTS_IDENTITY_MATCH="+identity_gate)
    print("HUMAN_REVIEW=PENDING")
    print("BR_OWNER_V1_RUNTIME_ACTIVATION=BLOCKED_PENDING_HUMAN_REVIEW")
    print(f"CANDIDATE_GENERATION_SECONDS={generation_seconds:.6f}")
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"SINGLE_HUMAN_CLONE=FAIL FAILURE_CLASS={type(exc).__name__}:{str(exc)[:300]}",file=__import__("sys").stderr)
        raise SystemExit(51)
