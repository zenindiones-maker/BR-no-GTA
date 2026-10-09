"""V23 bounded paired ICL ablation. No delivery, training or production authority.

Private reference audio and generated waveforms remain inside the authorized runner
workspace. Sanitized diagnostic receipts alone may be printed.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from app.services.owner_voice_speaker_identity_service import evaluate_clone_identity_gate
from app.services.owner_voice_audio_quality_service import pcm16_quality_metrics
from app.services.owner_voice_human_audition_pack_service import evaluate_segment_transcript_qa

SEED = 424242
CASES = (
    {"id":"phrase-gta-vice","spoken":"Hoje, no Gê Tê A seis, vamos explorar vaicy siti com muita atenção aos detalhes.", "language":"Portuguese"},
    {"id":"phrase-transition","spoken":"A história começa agora e cada detalhe dessa viagem faz uma grande diferença.", "language":"Portuguese"},
    {"id":"phrase-owner-energy","spoken":"Meu povo, chegou a hora de conhecer as novidades e entender o que realmente mudou.", "language":"Portuguese"},
)


def canonical_ptbr_cases() -> tuple[dict[str,Any],...]:
    return tuple({**row,"seed":SEED+i} for i,row in enumerate(CASES))


def _field(prompt:Any,key:str)->Any:
    return prompt.get(key) if isinstance(prompt,dict) else getattr(prompt,key,None)


def build_paired_prompts(anchor:Any, pronunciation:Any, prompt_factory:Any)->tuple[Any,Any]:
    for row in (anchor,pronunciation):
        if any(_field(row,key) is None for key in ("ref_code","ref_spk_embedding")):
            raise ValueError("QWEN_ABLATION_REFERENCE_INVALID")
        if not str(_field(row,"ref_text") or "").strip():
            raise ValueError("QWEN_ABLATION_REFERENCE_INVALID")
        if _field(row,"x_vector_only_mode") is True or _field(row,"icl_mode") is False:
            raise ValueError("QWEN_ABLATION_REFERENCE_INVALID")
    hybrid=prompt_factory(
        ref_code=_field(pronunciation,"ref_code"),
        ref_spk_embedding=_field(anchor,"ref_spk_embedding"),
        ref_text=_field(pronunciation,"ref_text"),
        x_vector_only_mode=False,
        icl_mode=True,
    )
    return anchor,hybrid


def select_verdict(rows:list[dict[str,Any]])->dict[str,Any]:
    """Reject unmatched, duplicated, substituted or incomplete A/B evidence.

    This is a structural verification, not a voice-identity or human approval.
    The same exact case and seed must appear once per A and B configuration.
    """
    if not isinstance(rows, list):
        raise ValueError("QWEN_ABLATION_INCOMPLETE_PAIRED_COMPARISON")
    expected = {
        (label, case["id"], case["seed"])
        for case in canonical_ptbr_cases()
        for label in ("A", "B")
    }
    observed = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("QWEN_ABLATION_INCOMPLETE_PAIRED_COMPARISON")
        key = (row.get("configuration"), row.get("case_id"), row.get("seed"))
        if (key[0] not in ("A", "B")
                or not isinstance(key[1], str)
                or type(key[2]) is not int
                or key not in expected
                or key in observed):
            raise ValueError("QWEN_ABLATION_INCOMPLETE_PAIRED_COMPARISON")
        observed.add(key)
    if observed != expected:
        raise ValueError("QWEN_ABLATION_INCOMPLETE_PAIRED_COMPARISON")
    a = [row for row in rows if row["configuration"] == "A"]
    b = [row for row in rows if row["configuration"] == "B"]
    return {
        "status": "HUMAN_PERCEPTUAL_REVIEW_REQUIRED",
        "voice_activated": False,
        "delivery_authorized": False,
        "all_a_identity_pass": all(x.get("identity_passed") is True for x in a),
        "all_b_identity_pass": all(x.get("identity_passed") is True for x in b),
    }


def run_private_ablation(
    *, model:Any, anchor_prompt:Any, pronunciation_prompt:Any, prompt_factory:Any,
    profile:dict[str,Any], canonical_embedding:list[float], workspace:Path,
    seed_setter:Any, normalize_16k:Any, identity_embedding:Any, stt:Any,
)->dict[str,Any]:
    """Paired seed/text/language comparisons, 3 trials per arm, never sends media."""
    import numpy as np
    import soundfile as sf

    if not workspace.is_dir() or workspace.is_symlink():
        raise ValueError("QWEN_ABLATION_PRIVATE_WORKSPACE_INVALID")
    a,b=build_paired_prompts(anchor_prompt,pronunciation_prompt,prompt_factory)
    prompts={"A":a,"B":b}
    rows=[]
    for index,case in enumerate(canonical_ptbr_cases()):
        for label in ("A","B"):
            seed_setter(int(case["seed"]))
            wavs,rate=model.generate_voice_clone(
                text=[case["spoken"]],
                language=[case["language"]],
                voice_clone_prompt=[prompts[label]],
                non_streaming_mode=True,
            )
            if len(wavs)!=1 or int(rate)<=0:
                raise RuntimeError("QWEN_ABLATION_INFERENCE_INVALID")
            wav=np.asarray(wavs[0],dtype=np.float32).reshape(-1)
            if not len(wav) or not np.isfinite(wav).all():
                raise RuntimeError("QWEN_ABLATION_AUDIO_INVALID")
            raw_path=workspace/f"v23-ablation-{index:02d}-{label}.wav"
            sf.write(str(raw_path),wav,int(rate),subtype="PCM_16")
            raw_path.chmod(0o600)
            pcm16_path=normalize_16k(raw_path,workspace/f"v23-ablation-{index:02d}-{label}-16k.wav",16000)
            pcm16_path.chmod(0o600)
            embedding=identity_embedding(stt[0],pcm16_path) if isinstance(stt,tuple) else identity_embedding(pcm16_path)
            identity=evaluate_clone_identity_gate(
                profile,clone_embedding=embedding,canonical_embedding=canonical_embedding,
            )
            metrics=pcm16_quality_metrics(raw_path)
            speech_model=stt[1] if isinstance(stt,tuple) else stt
            segments,_info=speech_model.transcribe(
                str(raw_path),language="pt",beam_size=5,vad_filter=True,
                word_timestamps=False,condition_on_previous_text=False,
            )
            observed=" ".join(str(getattr(x,"text","") or "").strip() for x in segments).strip()
            content=evaluate_segment_transcript_qa(
                expected=case["spoken"],observed=observed,language="pt",
            )
            rows.append({
                "configuration":label,"case_id":case["id"],"seed":case["seed"],
                "model_revision":"fd4b254389122332181a7c3db7f27e918eec64e3",
                "audio_sha256":sha256(raw_path.read_bytes()).hexdigest(),
                "identity_passed":bool(identity["passed"]),
                "speaker_similarity":float(identity["similarity_to_centroid"]),
                "reference_similarity":float(identity["similarity_to_reference"]),
                "identity_centroid_min":float(identity["centroid_min_similarity"]),
                "identity_reference_min":float(identity["reference_min_similarity"]),
                "content_passed":bool(content["passed"]),
                "character_error_rate":float(content["character_error_rate"]),
                "word_error_rate":float(content["word_error_rate"]),
                "duration_seconds":round(float(metrics["duration_seconds"]),4),
                "clipping_ratio":round(float(metrics["clipping_ratio"]),7),
                "rms_dbfs":round(float(metrics["rms_dbfs"]),4),
                "human_naturalness_review":"PENDING",
            })
    verdict=select_verdict(rows)
    report={
        "schema_version":"BRQwenPairedAblation/v23",
        "model":"Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        "model_revision":"fd4b254389122332181a7c3db7f27e918eec64e3",
        "source":"TELEGRAM_HUMAN_OWNER",
        "identity":"BR_OWNER_V1",
        "configuration_A":"ORIGINAL_ANCHOR_COMPLETE_ICL",
        "configuration_B":"LEGACY_MIXED_EMBEDDING_ACOUSTIC_CODES",
        "case_count":len(CASES),
        "rows":rows,
        "verdict":verdict,
        "telegram_send":False,
        "model_finetune":False,
        "voice_activated":False,
        "human_approval":"PENDING",
    }
    encoded=json.dumps(report,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()
    report["receipt_sha256"]=sha256(encoded).hexdigest()
    path=workspace/"v23-private-ablation.json"
    with path.open("x",encoding="utf-8") as f:
        json.dump(report,f,sort_keys=True,indent=2)
    path.chmod(0o600)
    # Summaries only; no audio/transcripts, biometric templates or owner reference content.
    for label in ("A","B"):
        subset=[row for row in rows if row["configuration"]==label]
        print("V23_ABLATION_SUMMARY="+json.dumps({
            "configuration":label,
            "trials":len(subset),
            "identity_passes":sum(r["identity_passed"] for r in subset),
            "content_passes":sum(r["content_passed"] for r in subset),
            "mean_speaker_similarity":round(sum(r["speaker_similarity"] for r in subset)/len(subset),6),
            "max_character_error_rate":max(r["character_error_rate"] for r in subset),
        },sort_keys=True))
    print("V23_ABLATION_RECEIPT_SHA256="+report["receipt_sha256"])
    print("V23_ABLATION_DELIVERY=NOT_ATTEMPTED")
    return report
