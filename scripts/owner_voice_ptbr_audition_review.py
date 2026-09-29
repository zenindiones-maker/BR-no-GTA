from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping


def normalize_ptbr_text(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", str(text or "").casefold())
    without_marks = "".join(ch for ch in folded if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^a-z0-9]+", " ", without_marks)
    return [token for token in cleaned.split() if token]


def word_error_rate(expected: str, observed: str) -> float:
    reference = normalize_ptbr_text(expected)
    hypothesis = normalize_ptbr_text(observed)
    if not reference:
        raise ValueError("EXPECTED_TEXT_REQUIRED")
    previous = list(range(len(hypothesis) + 1))
    for row, ref_word in enumerate(reference, start=1):
        current = [row]
        for col, hyp_word in enumerate(hypothesis, start=1):
            substitution = previous[col - 1] + (ref_word != hyp_word)
            insertion = current[col - 1] + 1
            deletion = previous[col] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return round(previous[-1] / len(reference), 6)


def build_variant_qa(
    *,
    expected_text: str,
    observed_text: str,
    detected_language: str,
    language_probability: float,
    audio_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    language = str(detected_language or "").strip().lower().replace("_", "-")
    probability = max(0.0, min(1.0, float(language_probability)))
    wer = word_error_rate(expected_text, observed_text)
    clipping = float(audio_metrics.get("clipping_ratio") or 0.0)
    speech_ratio = float(audio_metrics.get("speech_ratio") or 0.0)
    issues: list[str] = []
    if language not in {"pt", "pt-br"} or probability < 0.90:
        issues.append("NON_PORTUGUESE_OUTPUT")
    if wer > 0.25:
        issues.append("HIGH_WORD_ERROR_RATE")
    if clipping > 0.01:
        issues.append("OUTPUT_CLIPPING")
    if speech_ratio < 0.55:
        issues.append("LOW_OUTPUT_SPEECH_RATIO")
    return {
        "status": "FAIL" if issues else "PASS",
        "issues": issues,
        "locale_gate": "PT_BR_REQUIRED",
        "detected_language": language,
        "language_probability": probability,
        "word_error_rate": wer,
        "clipping_ratio": clipping,
        "speech_ratio": speech_ratio,
        "human_brazilian_accent_review_required": True,
        "human_voice_identity_review_required": True,
    }


def resolve_stt_model_path(
    *,
    manifest: Mapping[str, Any],
    qa_context_path,
):
    import json
    from pathlib import Path

    manifest_value = str(manifest.get("stt_model_path") or "").strip()
    if manifest_value:
        candidate = Path(manifest_value).expanduser()
        if candidate.is_dir():
            return candidate

    context_path = Path(qa_context_path).expanduser()
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("OWNER_PTBR_STT_LOCAL_MODEL_MISSING") from exc

    context_value = str(context.get("stt_model_path") or "").strip()
    if context_value:
        candidate = Path(context_value).expanduser()
        if candidate.is_dir():
            return candidate

    raise RuntimeError("OWNER_PTBR_STT_LOCAL_MODEL_MISSING")


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


def build_human_review_caption(*, label: str) -> str:
    normalized = str(label or "").strip().upper()
    if normalized not in {"A", "B", "C"}:
        raise ValueError("OWNER_PTBR_AUDITION_LABEL_INVALID")
    return (
        f"Teste {normalized} da sua voz em Português do Brasil. "
        "Ouça e escolha abaixo."
    )


def build_human_review_markup(*, label: str) -> dict[str, Any]:
    normalized = str(label or "").strip().upper()
    if normalized not in {"A", "B", "C"}:
        raise ValueError("OWNER_PTBR_AUDITION_LABEL_INVALID")
    return {
        "inline_keyboard": [
            [
                {
                    "text": "✅ É minha voz e o PT-BR está natural",
                    "callback_data": f"ov1:approve:{normalized}",
                }
            ],
            [
                {
                    "text": "❌ Não é minha voz",
                    "callback_data": f"ov1:reject_identity:{normalized}",
                },
                {
                    "text": "❌ Português/sotaque ruim",
                    "callback_data": f"ov1:reject_ptbr:{normalized}",
                },
            ],
        ]
    }


def _convert_to_voice_note(source, target):
    import subprocess
    from pathlib import Path

    source_path = Path(source)
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(source_path),
            "-vn", "-ac", "1", "-ar", "48000",
            "-c:a", "libopus", "-b:a", "48k", "-application", "voip",
            str(target_path),
        ],
        check=True,
        capture_output=True,
    )
    if not target_path.is_file() or target_path.stat().st_size <= 0:
        raise RuntimeError("OWNER_PTBR_VOICE_NOTE_CONVERSION_FAILED")
    return target_path


def _send_voice(
    *,
    bot_token: str,
    chat_id: int,
    path,
    filename: str,
    caption: str,
    reply_markup: Mapping[str, Any],
    reply_to_message_id: int | None = None,
) -> int:
    import json
    import requests

    data = {
        "chat_id": str(chat_id),
        "caption": caption,
        "reply_markup": json.dumps(
            dict(reply_markup),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "protect_content": "true",
    }
    if reply_to_message_id is not None:
        data["reply_parameters"] = json.dumps(
            {"message_id": int(reply_to_message_id)},
            separators=(",", ":"),
        )

    with open(path, "rb") as stream:
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendVoice",
            data=data,
            files={"voice": (filename, stream, "audio/ogg")},
            timeout=120,
        )
    if response.status_code != 200:
        raise RuntimeError("OWNER_PTBR_AUDITION_DELIVERY_FAILED")
    payload = response.json()
    result = payload.get("result") if isinstance(payload, dict) else None
    if payload.get("ok") is not True or not isinstance(result, dict):
        raise RuntimeError("OWNER_PTBR_AUDITION_DELIVERY_FAILED")
    message_id = int(result.get("message_id") or 0)
    if message_id <= 0:
        raise RuntimeError("OWNER_PTBR_AUDITION_DELIVERY_RECEIPT_INVALID")
    return message_id


def main() -> int:
    import json
    import os
    from pathlib import Path

    from app.services.owner_voice_audio_quality_service import pcm16_quality_metrics
    from scripts.owner_voice_chatterbox_ptbr_audition import (
        MODEL_ID,
        MODEL_REVISION,
        _load_reference_index_from_environment,
    )

    runner_temp = Path(os.environ.get("RUNNER_TEMP") or "/tmp").resolve()
    manifest_path = Path(
        os.environ.get("BR_OWNER_PTBR_AUDITION_SET")
        or runner_temp / "br-owner-voice" / "ptbr-audition-set.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("schema") != "OwnerVoicePtBrAuditionSet/v1"
        or manifest.get("voice_identity_id") != "BR_OWNER_V1"
        or manifest.get("reference_source") != "TELEGRAM"
        or manifest.get("locale") != "pt-BR"
        or manifest.get("language_id") != "pt"
        or manifest.get("model_id") != MODEL_ID
        or manifest.get("model_revision") != MODEL_REVISION
        or manifest.get("provider_default_voice_used") is not False
        or manifest.get("provider_preset_voice_used") is not False
        or manifest.get("generic_voice_fallback") is not False
    ):
        raise RuntimeError("OWNER_PTBR_AUDITION_SET_INVALID")

    token = str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN_NOT_MATERIALIZED")

    reference_index = _load_reference_index_from_environment()
    selected_input_id = int(manifest.get("selected_reference_input_id") or 0)
    source_row = next(
        (
            row for row in reference_index["references"]
            if int(row["telegram_input_id"]) == selected_input_id
        ),
        None,
    )
    if not isinstance(source_row, dict):
        raise RuntimeError("OWNER_PTBR_AUDITION_CHAT_PROVENANCE_MISSING")
    chat_id = int(source_row["telegram_chat_id"])

    from faster_whisper import WhisperModel

    qa_context_path = Path(
        os.environ.get("BR_OWNER_REFERENCE_QA_CONTEXT")
        or runner_temp / "br-owner-voice" / "reference-qa-context.json"
    )
    stt_model_path = resolve_stt_model_path(
        manifest=manifest,
        qa_context_path=qa_context_path,
    )

    stt = WhisperModel(
        str(stt_model_path),
        device="cpu",
        compute_type="int8",
        local_files_only=True,
    )

    expected_text = str(manifest.get("audition_text") or "").strip()
    reviewed: list[dict[str, Any]] = []
    for row in manifest.get("outputs") or ():
        path = Path(str(row.get("path") or ""))
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError("OWNER_PTBR_AUDITION_OUTPUT_MISSING")
        segments_iter, info = stt.transcribe(
            str(path),
            language=None,
            beam_size=5,
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=True,
        )
        segments = list(segments_iter)
        observed_text = " ".join(
            str(getattr(segment, "text", "") or "").strip()
            for segment in segments
            if str(getattr(segment, "text", "") or "").strip()
        )
        qa = build_variant_qa(
            expected_text=expected_text,
            observed_text=observed_text,
            detected_language=str(getattr(info, "language", "") or ""),
            language_probability=float(
                getattr(info, "language_probability", 0.0) or 0.0
            ),
            audio_metrics=pcm16_quality_metrics(path),
        )
        qa["transcription_confidence"] = _transcription_confidence(segments)
        reviewed.append({**dict(row), "qa": qa})

    passing = [row for row in reviewed if row["qa"]["status"] == "PASS"]
    if not passing:
        raise RuntimeError("OWNER_PTBR_AUDITION_NO_AUTOMATIC_PASS")

    deliveries: list[dict[str, Any]] = []
    labels = ("A", "B", "C")
    for row in passing:
        variant = int(row["variant"])
        label = labels[variant - 1]
        caption = build_human_review_caption(label=label)
        voice_note = _convert_to_voice_note(
            row["path"],
            runner_temp / "br-owner-voice" / "voice-notes" / f"BR_OWNER_V1_PTBR_{label}.ogg",
        )
        message_id = _send_voice(
            bot_token=token,
            chat_id=chat_id,
            path=voice_note,
            filename=f"BR_OWNER_V1_PTBR_{label}.ogg",
            caption=caption,
            reply_markup=build_human_review_markup(label=label),
            reply_to_message_id=int(source_row["telegram_message_id"]),
        )
        deliveries.append({
            "variant": variant,
            "label": label,
            "cfg_weight": float(row["cfg_weight"]),
            "telegram_message_id": message_id,
            "automatic_qa": row["qa"],
            "human_review": "PENDING",
            "telegram_delivery_type": "VOICE_NOTE",
            "review_callback_prefix": "ov1",
        })

    receipt = {
        "schema": "OwnerVoicePtBrAuditionReview/v1",
        "voice_identity_id": "BR_OWNER_V1",
        "reference_source": "TELEGRAM",
        "locale": "pt-BR",
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "automatic_pass_count": len(passing),
        "deliveries": deliveries,
        "human_voice_identity_review": "PENDING",
        "human_brazilian_accent_review": "PENDING",
        "human_fluency_review": "PENDING",
        "production_activation": "BLOCKED_PENDING_HUMAN_REVIEW",
        "observed_transcript_logged": False,
    }
    receipt_path = runner_temp / "br-owner-voice" / "ptbr-audition-review.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    try:
        receipt_path.chmod(0o600)
    except OSError:
        pass

    print(f"OWNER_PTBR_AUTOMATIC_PASS_COUNT={len(passing)}")
    print(f"OWNER_PTBR_TELEGRAM_DELIVERY_COUNT={len(deliveries)}")
    print("OWNER_PTBR_OBSERVED_TRANSCRIPT_LOGGED=NO")
    print("HUMAN_VOICE_IDENTITY_REVIEW=PENDING")
    print("HUMAN_BRAZILIAN_ACCENT_REVIEW=PENDING")
    print("HUMAN_PTBR_FLUENCY_REVIEW=PENDING")
    print("OWNER_PTBR_AUDITION_REVIEW=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            "OWNER_PTBR_AUDITION_REVIEW=FAIL "
            f"FAILURE_CLASS={str(exc).split(':', 1)[0]}",
            file=__import__("sys").stderr,
        )
        raise SystemExit(45)
