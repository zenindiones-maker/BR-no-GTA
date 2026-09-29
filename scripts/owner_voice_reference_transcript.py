from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable

from app.services.owner_voice_private_materialization_service import (
    OwnerVoicePrivateMaterializationError,
    materialize_telegram_owner_references,
    parse_owner_reference_index_secret,
)
from app.services.owner_voice_telegram_handoff_service import (
    parse_reference_envelope_b64,
)
from scripts.owner_voice_qwen_ephemeral_audition import select_latest_reference


TRANSCRIPT_SCHEMA = "OwnerVoicePrivateTranscript/v1"
DEFAULT_STT_MODEL = "small"
DEFAULT_CONTEXT_PATH = "/tmp/br-owner-voice/private-transcript-context.json"


def _valid_sha256(value: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("audio_sha256 must be a sha256 hex digest")
    return digest


def build_private_transcript_context(
    *,
    telegram_input_id: int,
    audio_sha256: str,
    transcript: str,
    language: str,
    language_probability: float,
    transcription_confidence: float,
    model_id: str,
) -> dict[str, Any]:
    input_id = int(telegram_input_id)
    if input_id <= 0:
        raise ValueError("telegram_input_id must be positive")

    digest = _valid_sha256(audio_sha256)
    text = " ".join(str(transcript or "").split()).strip()
    if len(text) < 4:
        raise ValueError("transcript is empty")

    normalized_language = str(language or "").strip().lower().replace("_", "-")
    if normalized_language not in {"pt", "pt-br"}:
        raise ValueError("reference transcript must be Portuguese")

    language_probability = float(language_probability)
    transcription_confidence = float(transcription_confidence)
    if not 0.70 <= language_probability <= 1.0:
        raise ValueError("language probability is insufficient")
    if not 0.65 <= transcription_confidence <= 1.0:
        raise ValueError("transcription confidence is insufficient")

    stt_model = str(model_id or "").strip()
    if not stt_model:
        raise ValueError("model_id is required")

    return {
        "schema": TRANSCRIPT_SCHEMA,
        "voice_identity_id": "BR_OWNER_V1",
        "telegram_input_id": input_id,
        "audio_sha256": digest,
        "language": normalized_language,
        "language_probability": round(language_probability, 6),
        "transcription_confidence": round(transcription_confidence, 6),
        "stt_provider": "faster-whisper",
        "stt_model": stt_model,
        "transcript": text,
        "private_only": True,
        "human_review_required": True,
    }


def _load_reference_index() -> dict[str, Any]:
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


def _normalize_reference(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    if not target.is_file() or target.stat().st_size <= 0:
        raise OwnerVoicePrivateMaterializationError(
            "OWNER_REFERENCE_NORMALIZATION_FAILED"
        )
    return target


def _transcription_confidence(segments: Iterable[Any]) -> float:
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
    if not values:
        return 0.0
    return sum(values) / len(values)


def main() -> int:
    token = str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise OwnerVoicePrivateMaterializationError(
            "TELEGRAM_BOT_TOKEN_NOT_MATERIALIZED"
        )

    runner_temp = Path(os.environ.get("RUNNER_TEMP") or "/tmp").resolve()
    repository_root = Path.cwd().resolve()
    index = _load_reference_index()
    materialized = materialize_telegram_owner_references(
        index,
        private_root=runner_temp / "br-owner-voice" / "transcript-references",
        repository_root=repository_root,
        telegram_bot_token=token,
    )
    selected = select_latest_reference(materialized["references"])
    normalized = _normalize_reference(
        Path(str(selected["runtime_path"])),
        runner_temp / "br-owner-voice" / "transcript-reference.wav",
    )

    from faster_whisper import WhisperModel

    model_id = str(os.environ.get("BR_OWNER_STT_MODEL") or DEFAULT_STT_MODEL).strip()
    model = WhisperModel(
        model_id,
        device="cpu",
        compute_type="int8",
        download_root=str(runner_temp / "br-owner-voice" / "stt-models"),
    )
    segments_iter, info = model.transcribe(
        str(normalized),
        language="pt",
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
    confidence = _transcription_confidence(segments)
    language = str(getattr(info, "language", "") or "pt")
    language_probability = float(
        getattr(info, "language_probability", 0.0) or 0.0
    )

    context = build_private_transcript_context(
        telegram_input_id=int(selected["telegram_input_id"]),
        audio_sha256=str(selected["sha256"]),
        transcript=transcript,
        language=language,
        language_probability=language_probability,
        transcription_confidence=confidence,
        model_id=model_id,
    )

    output = Path(
        os.environ.get("BR_OWNER_PRIVATE_TRANSCRIPT_CONTEXT")
        or DEFAULT_CONTEXT_PATH
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

    print("OWNER_REFERENCE_TRANSCRIPT=PASS")
    print(f"OWNER_REFERENCE_STT_MODEL={model_id}")
    print("OWNER_REFERENCE_TRANSCRIPT_TEXT_LOGGED=NO")
    print("OWNER_REFERENCE_TRANSCRIPT_PUBLIC_ARTIFACT=0")
    print("TRANSCRIPT_CONDITIONING_READY=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OwnerVoicePrivateMaterializationError, ValueError) as exc:
        print(
            "OWNER_REFERENCE_TRANSCRIPT=FAIL "
            f"FAILURE_CLASS={str(exc).split(':', 1)[0]}",
            file=sys.stderr,
        )
        raise SystemExit(42)
