from __future__ import annotations

import os
from pathlib import Path

from typing import Any, Iterable, Mapping

from app.services.owner_voice_audio_quality_service import score_owner_reference_quality
from app.services.owner_voice_clone_service import (
    CLIPPING_RATIO_MAX,
    SNR_DB_MIN,
    SPEECH_RATIO_MIN,
    select_owner_reference,
)


VOICE_IDENTITY_ID = "BR_OWNER_V1"
REFERENCE_SOURCE = "TELEGRAM"
EXTERNAL_LOCALE = "pt-BR"


def _language(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def reference_quality_upper_bound(metrics: Mapping[str, Any]) -> float:
    return score_owner_reference_quality(
        metrics,
        ptbr_probability=1.0,
        transcription_confidence=1.0,
    )


def should_stop_reference_asr(
    best_quality: float,
    remaining_upper_bounds: Iterable[float],
) -> bool:
    remaining=[float(value) for value in remaining_upper_bounds]
    if not remaining:
        return True
    return float(best_quality) > max(remaining)


def _cheap_reference_can_be_identity_grade(
    reference: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> bool:
    private_ref=str(reference.get("private_audio_ref") or "").strip()
    digest=str(reference.get("sha256") or "").strip().lower()
    return bool(
        int(reference.get("telegram_input_id") or 0)>0
        and private_ref.startswith(f"private://voice/{VOICE_IDENTITY_ID}/")
        and len(digest)==64
        and all(ch in "0123456789abcdef" for ch in digest)
        and reference.get("single_speaker") is not False
        and float(metrics.get("clipping_ratio") or 0.0)<=CLIPPING_RATIO_MAX
        and float(metrics.get("snr_db") or 0.0)>=SNR_DB_MIN
        and float(metrics.get("speech_ratio") or 0.0)>=SPEECH_RATIO_MIN
        and float(metrics.get("duration_seconds") or 0.0)>0.0
    )


def build_reference_candidate(
    *,
    reference: Mapping[str, Any],
    normalized_path: str,
    metrics: Mapping[str, Any],
    detected_language: str,
    language_probability: float,
    transcription_confidence: float,
    transcript: str,
) -> dict[str, Any]:
    text_present = bool(" ".join(str(transcript or "").split()).strip())
    lang = _language(detected_language)
    probability = max(0.0, min(1.0, float(language_probability)))
    confidence = max(0.0, min(1.0, float(transcription_confidence)))
    ptbr_probability = probability if lang in {"pt", "pt-br"} else 0.0
    quality_score = score_owner_reference_quality(
        metrics,
        ptbr_probability=ptbr_probability,
        transcription_confidence=confidence,
    )
    return {
        **dict(reference),
        **dict(metrics),
        "voice_identity_id": VOICE_IDENTITY_ID,
        "reference_source": REFERENCE_SOURCE,
        "locale": EXTERNAL_LOCALE,
        "runtime_path": str(normalized_path),
        "detected_language": lang,
        "language_probability": probability,
        "ptbr_probability": ptbr_probability,
        "transcription_confidence": confidence,
        "quality_score": quality_score,
        "transcript_private_only": True,
        "transcript_present": text_present,
    }


def build_reference_qa_context(
    candidates: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = [dict(row) for row in candidates]
    selected = select_owner_reference(rows)
    if selected.get("transcript_present") is not True:
        raise ValueError("OWNER_REFERENCE_TRANSCRIPT_REQUIRED")
    return {
        "schema": "OwnerVoiceReferenceQAContext/v1",
        "voice_identity_id": VOICE_IDENTITY_ID,
        "reference_source": REFERENCE_SOURCE,
        "locale": EXTERNAL_LOCALE,
        "selected_telegram_input_id": int(selected["telegram_input_id"]),
        "selected_audio_sha256": str(selected["sha256"]),
        "selected_private_audio_ref": str(selected["private_audio_ref"]),
        "selection_policy": str(selected["selection_policy"]),
        "latest_input_wins": False,
        "quality_score": float(selected["quality_score"]),
        "ptbr_probability": float(selected["ptbr_probability"]),
        "transcription_confidence": float(selected["transcription_confidence"]),
        "snr_db": float(selected.get("snr_db") or 0.0),
        "clipping_ratio": float(selected.get("clipping_ratio") or 0.0),
        "speech_ratio": float(selected.get("speech_ratio") or 0.0),
        "private_transcript_available": True,
    }


def _load_reference_index() -> dict[str, Any]:
    import json
    import os

    from app.services.owner_voice_private_materialization_service import (
        OwnerVoicePrivateMaterializationError,
        parse_owner_reference_index_secret,
    )
    from app.services.owner_voice_telegram_handoff_service import (
        parse_reference_envelope_b64,
    )

    envelope = str(
        os.environ.get("BR_OWNER_TELEGRAM_REFERENCE_ENVELOPE_B64") or ""
    ).strip()
    if envelope:
        decoded = parse_reference_envelope_b64(envelope)
        return parse_owner_reference_index_secret(
            json.dumps(decoded, ensure_ascii=False, sort_keys=True)
        )
    legacy = str(
        os.environ.get("BR_OWNER_TELEGRAM_REFERENCE_INDEX") or ""
    ).strip()
    if legacy:
        return parse_owner_reference_index_secret(legacy)
    raise OwnerVoicePrivateMaterializationError(
        "OWNER_TELEGRAM_REFERENCE_INDEX_NOT_MATERIALIZED"
    )


def _normalize_reference(source, target):
    import subprocess
    from pathlib import Path

    source = Path(source)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(source),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target),
        ],
        check=True,
        capture_output=True,
    )
    if not target.is_file() or target.stat().st_size <= 0:
        raise RuntimeError("OWNER_REFERENCE_NORMALIZATION_FAILED")
    return target


def _transcription_confidence(segments) -> float:
    import math

    word_probabilities: list[float] = []
    segment_probabilities: list[float] = []
    for segment in segments:
        for word in getattr(segment, "words", None) or ():
            probability = getattr(word, "probability", None)
            if isinstance(probability, (int, float)) and 0.0 <= float(probability) <= 1.0:
                word_probabilities.append(float(probability))
        avg_logprob = getattr(segment, "avg_logprob", None)
        if isinstance(avg_logprob, (int, float)) and math.isfinite(float(avg_logprob)):
            segment_probabilities.append(
                max(0.0, min(1.0, math.exp(float(avg_logprob))))
            )
    values = word_probabilities or segment_probabilities
    return (sum(values) / len(values)) if values else 0.0



def _audition_workspace(runner_temp: Path) -> Path:
    configured=str(os.environ.get("BR_OWNER_AUDITION_WORKSPACE") or "").strip()
    if configured:
        root=Path(configured).expanduser().resolve()
        root.mkdir(parents=True,exist_ok=True)
        return root
    from app.services.owner_voice_audition_handoff_service import run_scoped_workspace
    return run_scoped_workspace(
        runner_temp,
        github_run_id=str(os.environ.get("GITHUB_RUN_ID") or "local"),
        github_run_attempt=str(os.environ.get("GITHUB_RUN_ATTEMPT") or "1"),
    )

def _write_env(values: Mapping[str,Any]) -> None:
    target=str(os.environ.get("GITHUB_ENV") or "").strip()
    if not target:
        return
    with open(target,"a",encoding="utf-8") as stream:
        for key,value in values.items():
            stream.write(f"{key}={value}\n")


def _ensure_stt_model(cache_root: Path, model_id: str) -> tuple[Path,int]:
    import shutil
    from faster_whisper.utils import download_model

    safe=model_id.replace("/","--")
    target=(cache_root/"stt"/safe).resolve()
    if (target/"model.bin").is_file() and (target/"config.json").is_file():
        return target,0
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    os.environ["HF_HUB_OFFLINE"]="0"
    path=Path(download_model(model_id,output_dir=str(target))).resolve()
    if not (path/"model.bin").is_file() or not (path/"config.json").is_file():
        raise RuntimeError("STT_PUBLIC_MODEL_CACHE_INVALID")
    return path,1


def main() -> int:
    import json
    import time
    from pathlib import Path

    from app.services.owner_voice_audio_quality_service import pcm16_quality_metrics
    from app.services.owner_voice_audition_ledger_store import store_from_environment
    from app.services.owner_voice_audition_performance_service import (
        GitBackedReferenceSelectionReceiptLedger,
        build_reference_selection_receipt,
        build_selection_policy_hash,
        build_stt_contract_hash,
        validate_reference_selection_receipt,
    )
    from app.services.owner_voice_private_materialization_service import (
        OwnerVoicePrivateMaterializationError,
        materialize_selected_telegram_owner_reference,
        materialize_telegram_owner_references,
    )
    from faster_whisper import WhisperModel

    started=time.monotonic()
    token = str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise OwnerVoicePrivateMaterializationError(
            "TELEGRAM_BOT_TOKEN_NOT_MATERIALIZED"
        )

    runner_temp = Path(os.environ.get("RUNNER_TEMP") or "/tmp").resolve()
    audition_workspace=_audition_workspace(runner_temp)
    repository_root = Path.cwd().resolve()
    index = _load_reference_index()
    reference_set_digest=str(index.get("index_sha256") or "").lower()
    selection_policy_hash=build_selection_policy_hash()
    model_id = str(os.environ.get("BR_OWNER_STT_MODEL") or "large-v3-turbo").strip()
    stt_contract_hash=build_stt_contract_hash(model_id)

    cache_root=Path(
        os.environ.get("BR_OWNER_PUBLIC_MODEL_CACHE")
        or Path.home()/".cache"/"br-owner-voice"/"hf-public"
    ).resolve()
    stt_model_path,stt_network_download_count=_ensure_stt_model(cache_root,model_id)
    _write_env({
        "BR_OWNER_STT_MODEL_PATH":str(stt_model_path),
        "STT_MODEL_DOWNLOAD_COUNT":stt_network_download_count,
        "STT_NETWORK_DOWNLOAD_COUNT":stt_network_download_count,
    })

    store=store_from_environment(
        repo_root=repository_root,
        workspace=audition_workspace/"reference-selection-ledger",
    )
    selection_ledger=GitBackedReferenceSelectionReceiptLedger(store)
    cached=selection_ledger.load()
    cache_state="MISS"
    context=None
    asr_count=0
    total_count=len(index.get("references") or [])

    if isinstance(cached,dict) and validate_reference_selection_receipt(
        cached,
        reference_set_digest=reference_set_digest,
        selection_policy_hash=selection_policy_hash,
        stt_contract_hash=stt_contract_hash,
    ):
        selected=materialize_selected_telegram_owner_reference(
            index,
            selected_telegram_input_id=int(cached["selected_telegram_input_id"]),
            private_root=audition_workspace/"qa-selected-reference",
            repository_root=repository_root,
            telegram_bot_token=token,
        )
        if str(selected.get("sha256") or "").lower()==str(cached["selected_audio_sha256"]).lower():
            normalized=_normalize_reference(
                selected["runtime_path"],
                audition_workspace/"qa-normalized"/"selected-reference.wav",
            )
            metrics=pcm16_quality_metrics(normalized)
            if _cheap_reference_can_be_identity_grade(selected,metrics):
                context={
                    "schema":"OwnerVoiceReferenceQAContext/v1",
                    "voice_identity_id":VOICE_IDENTITY_ID,
                    "reference_source":REFERENCE_SOURCE,
                    "locale":EXTERNAL_LOCALE,
                    "selected_telegram_input_id":int(cached["selected_telegram_input_id"]),
                    "selected_audio_sha256":str(cached["selected_audio_sha256"]),
                    "selected_private_audio_ref":str(selected["private_audio_ref"]),
                    "selection_policy":"QUALITY_FIRST_DETERMINISTIC",
                    "latest_input_wins":False,
                    "quality_score":float(cached["quality_score"]),
                    "ptbr_probability":float(cached["ptbr_probability"]),
                    "transcription_confidence":float(cached["transcription_confidence"]),
                    "snr_db":float(metrics.get("snr_db") or 0.0),
                    "clipping_ratio":float(metrics.get("clipping_ratio") or 0.0),
                    "speech_ratio":float(metrics.get("speech_ratio") or 0.0),
                    "private_transcript_available":False,
                }
                cache_state="HIT"
        else:
            cache_state="INVALID"

    if context is None:
        if isinstance(cached,dict):
            cache_state="INVALID"
        materialized = materialize_telegram_owner_references(
            index,
            private_root=audition_workspace / "qa-references",
            repository_root=repository_root,
            telegram_bot_token=token,
        )
        stt = WhisperModel(
            str(stt_model_path),
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
            num_workers=1,
            local_files_only=True,
        )

        prepared: list[dict[str, Any]] = []
        for reference in materialized["references"]:
            input_id = int(reference["telegram_input_id"])
            normalized = _normalize_reference(
                reference["runtime_path"],
                audition_workspace / "qa-normalized" / f"reference-{input_id}.wav",
            )
            metrics = pcm16_quality_metrics(normalized)
            if not _cheap_reference_can_be_identity_grade(reference,metrics):
                continue
            prepared.append({
                "reference":dict(reference),
                "normalized_path":str(normalized),
                "metrics":dict(metrics),
                "upper_bound":reference_quality_upper_bound(metrics),
            })

        prepared.sort(key=lambda row:(
            -float(row["upper_bound"]),
            str(row["reference"].get("sha256") or ""),
            int(row["reference"].get("telegram_input_id") or 0),
        ))
        candidates: list[dict[str, Any]] = []
        for position,item in enumerate(prepared):
            segments_iter, info = stt.transcribe(
                str(item["normalized_path"]),
                language=None,
                beam_size=5,
                vad_filter=True,
                word_timestamps=True,
                condition_on_previous_text=True,
            )
            segments = list(segments_iter)
            asr_count+=1
            transcript = " ".join(
                str(getattr(segment, "text", "") or "").strip()
                for segment in segments
                if str(getattr(segment, "text", "") or "").strip()
            )
            candidate = build_reference_candidate(
                reference=item["reference"],
                normalized_path=str(item["normalized_path"]),
                metrics=item["metrics"],
                detected_language=str(getattr(info, "language", "") or ""),
                language_probability=float(
                    getattr(info, "language_probability", 0.0) or 0.0
                ),
                transcription_confidence=_transcription_confidence(segments),
                transcript=transcript,
            )
            candidates.append(candidate)
            try:
                provisional=build_reference_qa_context(candidates)
            except ValueError:
                provisional=None
            remaining_bounds=[
                float(row["upper_bound"])
                for row in prepared[position+1:]
            ]
            if (
                provisional is not None
                and should_stop_reference_asr(
                    float(provisional["quality_score"]),
                    remaining_bounds,
                )
            ):
                break

        selected_context=build_reference_qa_context(candidates)
        context={
            **selected_context,
            "private_transcript_available":True,
        }
        receipt=build_reference_selection_receipt(
            reference_set_digest=reference_set_digest,
            selection_policy_hash=selection_policy_hash,
            stt_contract_hash=stt_contract_hash,
            selected_telegram_input_id=int(context["selected_telegram_input_id"]),
            selected_audio_sha256=str(context["selected_audio_sha256"]),
            quality_score=float(context["quality_score"]),
            ptbr_probability=float(context["ptbr_probability"]),
            transcription_confidence=float(context["transcription_confidence"]),
        )
        selection_ledger.persist(receipt)

    context={
        **dict(context),
        "stt_model_path":str(stt_model_path),
        "stt_model_id":model_id,
        "stt_reuse_mode":"EXACT_SHARED_MODEL_PATH",
        "reference_total_count":total_count,
        "reference_asr_count":asr_count,
        "reference_selection_cache":cache_state,
    }
    output = Path(
        os.environ.get("BR_OWNER_REFERENCE_QA_CONTEXT")
        or audition_workspace / "reference-qa-context.json"
    ).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(context, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    try:
        output.chmod(0o600)
    except OSError:
        pass

    elapsed=time.monotonic()-started
    _write_env({
        "REFERENCE_SELECTION_CACHE_HIT":"true" if cache_state=="HIT" else "false",
        "REFERENCE_ASR_COUNT":asr_count,
        "REFERENCE_QA_SECONDS":round(elapsed,6),
    })

    print("OWNER_AUDITION_WORKSPACE_SCOPE=PASS")
    print(f"OWNER_REFERENCE_QA_COUNT={asr_count}")
    print(f"OWNER_REFERENCE_TOTAL_COUNT={total_count}")
    print(f"OWNER_REFERENCE_ASR_COUNT={asr_count}")
    print(f"REFERENCE_SELECTION_CACHE={cache_state}")
    print(f"STT_MODEL_DOWNLOAD_COUNT={stt_network_download_count}")
    print(f"STT_NETWORK_DOWNLOAD_COUNT={stt_network_download_count}")
    print(f"BR_OWNER_STT_MODEL_PATH={stt_model_path}")
    print("OWNER_REFERENCE_QA_EXACT_BRANCH_AND_BOUND=PASS")
    print("OWNER_REFERENCE_SELECTION_POLICY=QUALITY_FIRST_DETERMINISTIC")
    print("OWNER_REFERENCE_LATEST_INPUT_WINS=false")
    print("OWNER_REFERENCE_SOURCE=TELEGRAM")
    print("OWNER_REFERENCE_TARGET_LOCALE=pt-BR")
    print("OWNER_REFERENCE_QA=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            "OWNER_REFERENCE_QA=FAIL "
            f"FAILURE_CLASS={str(exc).split(':', 1)[0]}",
            file=__import__("sys").stderr,
        )
        raise SystemExit(43)
