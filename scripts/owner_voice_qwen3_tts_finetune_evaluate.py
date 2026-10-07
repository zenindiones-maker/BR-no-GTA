from __future__ import annotations

import json
import os
import re
from pathlib import Path

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

from app.services.owner_voice_audio_quality_service import pcm16_quality_metrics
from app.services.owner_voice_human_audition_pack_service import evaluate_short_candidate
from app.services.owner_voice_speaker_identity_service import evaluate_clone_identity_gate
from scripts.owner_voice_single_human_clone import (
    SHORT_TEXT,
    VOICE_IDENTITY_ID,
    _embedding,
    _ffmpeg,
    _load_speaker_model,
    _load_stt,
    _sha256,
    _vad_ratio,
)


def _checkpoint_number(path:Path)->int:
    match=re.search(r"checkpoint-(\\d+)$",path.name)
    return int(match.group(1)) if match else -1


def main()->int:
    workspace=Path(os.environ["BR_OWNER_FINETUNE_PRIVATE_WORKSPACE"]).resolve()
    model_root=Path(os.environ["BR_OWNER_FINETUNE_MODEL_CANDIDATE"]).resolve()
    identity=json.loads(Path(os.environ["BR_OWNER_FINETUNE_IDENTITY_PROFILE_PRIVATE"]).read_text(encoding="utf-8"))
    dataset_manifest=json.loads(Path(os.environ["BR_OWNER_FINETUNE_DATASET_MANIFEST"]).read_text(encoding="utf-8"))
    cache=Path(os.environ["BR_OWNER_PUBLIC_MODEL_CACHE"]).resolve()
    profile=dict(identity["profile"])
    canonical_embedding=list(identity["canonical_embedding"])

    checkpoints=sorted(
        [path for path in model_root.rglob("checkpoint-*") if path.is_dir()],
        key=_checkpoint_number,
    )
    if not checkpoints:
        raise RuntimeError("OWNER_FINETUNE_NO_CHECKPOINTS")

    verifier=_load_speaker_model(cache)
    stt=_load_stt(cache)
    qualified=[]
    observations=[]
    for checkpoint in checkpoints:
        model=Qwen3TTSModel.from_pretrained(
            str(checkpoint),
            device_map="cuda:0",
            dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
            attn_implementation="sdpa",
        )
        wavs,sr=model.generate_custom_voice(
            text=SHORT_TEXT,
            language="Portuguese",
            speaker="BR_OWNER_V1",
        )
        if len(wavs)!=1:
            raise RuntimeError("OWNER_FINETUNE_EVAL_OUTPUT_COUNT_INVALID")
        candidate=workspace/"evaluation"/checkpoint.name/"CLONE.wav"
        candidate.parent.mkdir(parents=True,exist_ok=True)
        sf.write(str(candidate),wavs[0],int(sr),subtype="PCM_16")
        candidate16=_ffmpeg(candidate,candidate.with_name("CLONE-16k.wav"),16000)
        clone_embedding=_embedding(verifier,candidate16)
        gate=evaluate_clone_identity_gate(
            profile,
            clone_embedding=clone_embedding,
            canonical_embedding=canonical_embedding,
        )
        observations.append({
            "checkpoint":checkpoint.name,
            "similarity_to_centroid":gate["similarity_to_centroid"],
            "similarity_to_reference":gate["similarity_to_reference"],
            "identity_pass":gate["passed"] is True,
        })
        print(
            f"OWNER_FINETUNE_CHECKPOINT={checkpoint.name} "
            f"CENTROID={gate['similarity_to_centroid']} "
            f"REFERENCE={gate['similarity_to_reference']} "
            f"IDENTITY={'PASS' if gate['passed'] else 'FAIL'}"
        )
        if gate["passed"] is not True:
            del model
            torch.cuda.empty_cache()
            continue

        metrics=pcm16_quality_metrics(candidate16)
        seg_iter,info=stt.transcribe(
            str(candidate16),language="pt",beam_size=1,vad_filter=True,
            word_timestamps=False,condition_on_previous_text=False,
        )
        segments=list(seg_iter)
        transcript=" ".join(
            str(getattr(seg,"text","") or "").strip()
            for seg in segments
            if str(getattr(seg,"text","") or "").strip()
        )
        qa=evaluate_short_candidate({
            "candidate_id":checkpoint.name,
            "audio_sha256":_sha256(candidate),
            "voice_identity_id":VOICE_IDENTITY_ID,
            "provider_default_voice_used":False,
            "provider_preset_voice_used":False,
            "generic_voice_fallback":False,
            "detected_language":str(getattr(info,"language","pt") or "pt"),
            "language_probability":float(getattr(info,"language_probability",0.0) or 0.0),
            "vad_speech_ratio":_vad_ratio(segments,float(metrics.get("duration_seconds") or 0.0)),
            "expected_text":SHORT_TEXT,
            "observed_text":transcript,
            "audio_metrics":metrics,
            "speaker_similarity":{
                "status":"PASS",
                "score":gate["similarity_to_centroid"],
                "certifies_identity":True,
            },
        })
        if qa["eligible"] is True:
            margin=min(
                float(gate["similarity_to_centroid"])-float(gate["centroid_min_similarity"]),
                float(gate["similarity_to_reference"])-float(gate["reference_min_similarity"]),
            )
            qualified.append((margin,gate,candidate,checkpoint))
        del model
        torch.cuda.empty_cache()

    receipt=workspace/"evaluation"/"checkpoint-evaluation.json"
    receipt.parent.mkdir(parents=True,exist_ok=True)
    receipt.write_text(json.dumps({
        "schema_version":"OwnerVoiceQwen3TTSFineTuneEvaluation/v1",
        "voice_identity_id":"BR_OWNER_V1",
        "observed_checkpoints":observations,
        "qualified_count":len(qualified),
    },sort_keys=True,indent=2)+"\n",encoding="utf-8")

    if not qualified:
        print("OWNER_QWEN3_TTS_FINETUNE_IDENTITY_GATE=FAIL")
        raise RuntimeError("OWNER_FINETUNE_NO_QUALIFIED_CHECKPOINT")

    qualified.sort(key=lambda item:(-item[0],-_checkpoint_number(item[3])))
    _margin,gate,candidate,checkpoint=qualified[0]
    delivery={
        "schema_version":"OwnerVoiceSingleCloneCandidate/v1",
        "clone_id":f"BR_OWNER_V1_FINETUNE_{os.environ.get('GITHUB_RUN_ID','local')}",
        "voice_identity_id":"BR_OWNER_V1",
        "reference_source":"TELEGRAM_HUMAN_OWNER",
        "canonical_reference_telegram_input_id":int(dataset_manifest["canonical_reference_telegram_input_id"]),
        "canonical_reference_sha256":str(dataset_manifest["canonical_reference_sha256"]),
        "canonical_reference_source_message_id":int(dataset_manifest["canonical_reference_source_message_id"]),
        "telegram_chat_id":int(dataset_manifest["telegram_chat_id"]),
        "clone_path":str(candidate),
        "clone_sha256":_sha256(candidate),
        "clone_identity_gate":"PASS",
        "content_audio_prescreen":"PASS",
        "clone_similarity_to_centroid":gate["similarity_to_centroid"],
        "clone_similarity_to_reference":gate["similarity_to_reference"],
        "clone_centroid_threshold":gate["centroid_min_similarity"],
        "clone_reference_threshold":gate["reference_min_similarity"],
        "text":SHORT_TEXT,
        "generation":{
            "engine":"QWEN3_TTS_12HZ_1_7B_FINE_TUNED",
            "clone_mode":"SINGLE_SPEAKER_FULL_SFT",
            "speaker":"BR_OWNER_V1",
            "checkpoint":checkpoint.name,
            "reference_source":"TELEGRAM_HUMAN_OWNER",
            "runtime_activation":False,
        },
    }
    manifest=workspace/"single-clone-manifest.json"
    manifest.write_text(json.dumps(delivery,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    out=str(os.environ.get("GITHUB_OUTPUT") or "").strip()
    if out:
        with open(out,"a",encoding="utf-8") as stream:
            stream.write(f"manifest_path={manifest}\n")
            stream.write(f"selected_checkpoint={checkpoint}\n")
    print("OWNER_QWEN3_TTS_FINETUNE_IDENTITY_GATE=PASS")
    print("OWNER_QWEN3_TTS_FINETUNE_CONTENT_GATE=PASS")
    print("HUMAN_REVIEW=PENDING")
    print("RUNTIME_ACTIVATION=BLOCKED")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
