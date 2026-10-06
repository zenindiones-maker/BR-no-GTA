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

def main() -> int:
    import json
    import os
    from pathlib import Path

    from app.services.owner_voice_audio_quality_service import pcm16_quality_metrics
    from app.services.owner_voice_private_materialization_service import (
        OwnerVoicePrivateMaterializationError,
        materialize_telegram_owner_references,
    )

    token = str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise OwnerVoicePrivateMaterializationError(
            "TELEGRAM_BOT_TOKEN_NOT_MATERIALIZED"
        )

    runner_temp = Path(os.environ.get("RUNNER_TEMP") or "/tmp").resolve()
    audition_workspace=_audition_workspace(runner_temp)
    repository_root = Path.cwd().resolve()
    index = _load_reference_index()
    materialized = materialize_telegram_owner_references(
        index,
        private_root=audition_workspace / "qa-references",
        repository_root=repository_root,
        telegram_bot_token=token,
    )

    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model

    model_id = str(os.environ.get("BR_OWNER_STT_MODEL") or "small").strip()
    stt_model_root = audition_workspace / "stt-model"
    stt_model_path = download_model(
        model_id,
        output_dir=str(stt_model_root),
    )
    stt = WhisperModel(
        str(stt_model_path),
        device="cpu",
        compute_type="int8",
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
    for index,item in enumerate(prepared):
        segments_iter, info = stt.transcribe(
            str(item["normalized_path"]),
            language=None,
            beam_size=5,
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=True,
        )
        segments = list(segments_iter)
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
            for row in prepared[index+1:]
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
    context = {
        **selected_context,
        "stt_model_path": str(stt_model_path),
        "stt_model_id": model_id,
        "stt_reuse_mode": "LOCAL_FILES_ONLY_BRANCH_AND_BOUND",
        "reference_total_count":len(materialized["references"]),
        "reference_audio_eligible_count":len(prepared),
        "reference_asr_count":len(candidates),
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

    print("OWNER_AUDITION_WORKSPACE_SCOPE=PASS")
    print(f"OWNER_REFERENCE_QA_COUNT={len(candidates)}")
    print(f"OWNER_REFERENCE_TOTAL_COUNT={len(materialized['references'])}")
    print(f"OWNER_REFERENCE_ASR_COUNT={len(candidates)}")
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
