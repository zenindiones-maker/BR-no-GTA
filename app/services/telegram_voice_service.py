from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
from typing import Any, Callable

from app.services.speech.service import analyze_speech
from app.services.telegram_ingress_policy_service import parse_governed_telegram_ingress
from app.services.voice_egress_policy import apply_voice_egress_policy
from app.services.voice_plane_contracts import VoiceSynthesisRequest, VoiceTurnEnvelope


def _voice_attachment(message: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("voice", "audio"):
        value = message.get(key)
        if isinstance(value, dict) and str(value.get("file_id") or "").strip():
            return value
    return None


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_telegram_voice_audio(
    source: Path,
    target: Path,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    runner(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(source),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target),
        ],
        check=True,
        capture_output=True,
    )
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("VOICE_AUDIO_NORMALIZATION_FAILED")
    return target


def encode_telegram_voice_ogg_opus(
    source: Path,
    target: Path,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    runner(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(source),
            "-vn", "-c:a", "libopus", "-b:a", "48k", "-ac", "1", "-ar", "48000",
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("TTS_AUDIO_INVALID")
    return target


def process_telegram_voice_turn(
    *,
    update: dict[str, Any],
    allowed_user_id: int | None,
    state: dict[str, Any],
    telegram: Any,
    speech_provider: Any,
    harness_turn: Callable[..., dict[str, Any]],
    tts_provider: Any,
    work_dir: str | Path,
    audio_normalizer: Callable[[Path, Path], Path] = normalize_telegram_voice_audio,
    audio_encoder: Callable[[Path, Path], Path] = encode_telegram_voice_ogg_opus,
) -> dict[str, Any]:
    ingress = parse_governed_telegram_ingress(
        update,
        allowed_user_id=allowed_user_id,
        state=state,
    )
    if ingress is None or not ingress.accepted:
        raise PermissionError("authorized Telegram human/chat required")

    attachment = _voice_attachment(ingress.message)
    if attachment is None:
        raise ValueError("Telegram voice/audio attachment required")

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    source = Path(telegram.materialize_file(str(attachment["file_id"])))
    if not source.is_file():
        raise RuntimeError("TELEGRAM_GET_FILE_FAILED")

    normalized = audio_normalizer(source, work / "voice-input.wav")
    analysis, _qa = analyze_speech(
        normalized,
        provider=speech_provider,
        language="pt-BR",
    )
    transcript = " ".join(
        segment.text.strip()
        for segment in analysis.segments
        if segment.text.strip()
    ).strip()
    if not transcript:
        raise RuntimeError("STT_FAILED")

    unique_id = str(attachment.get("file_unique_id") or attachment.get("file_id") or "")
    seed = f"{ingress.chat_id}:{ingress.message.get('message_id')}:{unique_id}".encode("utf-8")
    turn_id = "voice-" + hashlib.sha256(seed).hexdigest()[:20]
    duration_seconds = float(attachment.get("duration") or analysis.duration_seconds)
    envelope = VoiceTurnEnvelope(
        turn_id=turn_id,
        conversation_id=f"telegram:{ingress.chat_id}",
        surface="TELEGRAM",
        speaker_identity=f"telegram-user:{ingress.user_id}",
        authorized_human=True,
        audio_asset_ref=f"ephemeral://telegram/{unique_id or turn_id}",
        audio_sha256=_hash_file(source),
        audio_format=source.suffix.lstrip(".") or "telegram-voice",
        duration_seconds=duration_seconds,
        transcript=transcript,
        transcript_language=analysis.source_language,
        transcript_confidence=float(analysis.quality.transcription_confidence),
        requested_capability="harness.voice.turn",
        requested_action="EXECUTION",
    )

    canonical = harness_turn(
        transcript,
        conversation_id=envelope.conversation_id,
        surface="TELEGRAM",
        correlation_id=turn_id,
    )
    if str(canonical.get("authority") or "").lower() != "deepseek_harness":
        raise RuntimeError("VOICE_AUTHORITY_ESCAPE")
    canonical_text = str(
        canonical.get("canonical_text")
        or canonical.get("answer")
        or canonical.get("text")
        or ""
    ).strip()
    if not canonical_text:
        raise RuntimeError("HARNESS_EMPTY_RESULT")

    egress = apply_voice_egress_policy(
        canonical_text=canonical_text,
        action_summary=str(canonical.get("spoken_summary") or "").strip() or None,
        mode="ACTION_FIRST",
    )
    request = VoiceSynthesisRequest(
        voice_identity_id=str(canonical.get("voice_identity_id") or "voice-b-control"),
        text=egress.spoken_response_text,
        language="pt-BR",
        usage="INTERACTIVE",
        rate=1.0,
        style="ACTION_FIRST",
        segment_id=turn_id,
        correlation_id=turn_id,
    )
    raw_audio = work / "voice-reply.wav"
    tts = tts_provider.synthesize(request, raw_audio)
    tts_path = Path(str(tts.get("audio_path") or raw_audio))
    ogg = audio_encoder(tts_path, work / "voice-reply.ogg")
    send_receipt = telegram.send_voice(
        chat_id=ingress.chat_id,
        voice_path=ogg,
        caption=None,
    )
    return {
        "schema": "TelegramVoiceTurnResult/v1",
        "status": "COMPLETED",
        "authority": "deepseek_harness",
        "execution_id": canonical.get("execution_id"),
        "voice_turn": envelope.to_dict(),
        "canonical_text": canonical_text,
        "spoken_response_text": egress.spoken_response_text,
        "tts_provider": str(getattr(tts_provider, "provider_id", "unknown")),
        "tts_model": str(getattr(tts_provider, "model_id", "unknown")),
        "spoken_audio_sha256": _hash_file(ogg),
        "send_voice": send_receipt,
        "raw_voice_persisted": False,
    }
