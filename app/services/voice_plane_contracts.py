from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

VOICE_TURN_ENVELOPE_VERSION = "VoiceTurnEnvelope/v1"
VOICE_TURN_RESULT_VERSION = "VoiceTurnResult/v1"
VOICE_IDENTITY_PROFILE_VERSION = "VoiceIdentityProfile/v1"
VOICE_SYNTHESIS_REQUEST_VERSION = "VoiceSynthesisRequest/v1"
VOICE_ENROLLMENT_QA_VERSION = "VoiceEnrollmentQA/v1"
VOICE_TURN_TELEMETRY_VERSION = "VoiceTurnTelemetry/v1"

VOICE_USAGES = frozenset({
    "INTERACTIVE", "LONG_FORM", "AUDITION", "PRONUNCIATION_TEST",
})


class ConsentStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"


def _nonempty(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _sha256(value: str, field: str) -> str:
    text = _nonempty(value, field).lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"{field} must be a sha256 hex digest")
    return text


def _private_ref(value: str, field: str) -> str:
    text = _nonempty(value, field)
    if not text.startswith("private://"):
        raise ValueError(f"{field} must use private:// storage")
    return text


@dataclass(frozen=True)
class VoiceTurnEnvelope:
    turn_id: str
    conversation_id: str
    surface: str
    speaker_identity: str
    authorized_human: bool
    audio_asset_ref: str
    audio_sha256: str
    audio_format: str
    duration_seconds: float
    transcript: str
    transcript_language: str
    transcript_confidence: float
    intent: str | None = None
    requested_capability: str | None = None
    requested_action: str | None = None
    requires_confirmation: bool = False
    authorization_ref: str | None = None
    execution_id: str | None = None
    created_at: str | None = None
    schema: str = VOICE_TURN_ENVELOPE_VERSION

    def __post_init__(self) -> None:
        _nonempty(self.turn_id, "turn_id")
        _nonempty(self.conversation_id, "conversation_id")
        _nonempty(self.surface, "surface")
        _nonempty(self.speaker_identity, "speaker_identity")
        _sha256(self.audio_sha256, "audio_sha256")
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if not 0.0 <= float(self.transcript_confidence) <= 1.0:
            raise ValueError("transcript_confidence must be between 0 and 1")
        _nonempty(self.transcript, "transcript")
        _nonempty(self.transcript_language, "transcript_language")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VoiceTurnResult:
    turn_id: str
    conversation_id: str
    status: str
    canonical_text: str
    execution_id: str | None
    artifact_refs: tuple[str, ...]
    spoken_response_text: str
    spoken_audio_ref: str | None
    spoken_audio_sha256: str | None
    tts_provider: str | None
    tts_model: str | None
    voice_identity_id: str | None
    latency_metrics: dict[str, float]
    schema: str = VOICE_TURN_RESULT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VoiceIdentityProfile:
    voice_identity_id: str
    owner_class: str
    language: str
    source_audio_refs: tuple[str, ...]
    source_audio_sha256s: tuple[str, ...]
    source_transcript_sha256s: tuple[str, ...]
    consent_status: ConsentStatus
    consent_timestamp: str | None
    clone_provider: str | None
    clone_model: str | None
    clone_model_revision: str | None
    voice_prompt_ref: str | None
    voice_prompt_sha256: str | None
    quality_status: str
    created_at: str
    updated_at: str
    schema: str = VOICE_IDENTITY_PROFILE_VERSION

    def __post_init__(self) -> None:
        _nonempty(self.voice_identity_id, "voice_identity_id")
        _nonempty(self.owner_class, "owner_class")
        _nonempty(self.language, "language")
        if len(self.source_audio_refs) != len(self.source_audio_sha256s):
            raise ValueError("source audio refs and hashes must have equal length")
        for ref in self.source_audio_refs:
            _private_ref(ref, "source_audio_ref")
        for digest in self.source_audio_sha256s:
            _sha256(digest, "source_audio_sha256")
        for digest in self.source_transcript_sha256s:
            _sha256(digest, "source_transcript_sha256")
        if self.voice_prompt_ref is not None:
            _private_ref(self.voice_prompt_ref, "voice_prompt_ref")
        if self.voice_prompt_sha256 is not None:
            _sha256(self.voice_prompt_sha256, "voice_prompt_sha256")
        if self.consent_status is ConsentStatus.APPROVED and not self.consent_timestamp:
            raise ValueError("approved consent requires consent_timestamp")

    @property
    def reusable_clone_allowed(self) -> bool:
        return bool(
            self.consent_status is ConsentStatus.APPROVED
            and self.source_audio_refs
            and self.voice_prompt_ref
            and self.voice_prompt_sha256
            and self.quality_status not in {"FAIL", "REJECTED"}
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["consent_status"] = self.consent_status.value
        return payload


@dataclass(frozen=True)
class VoiceSynthesisRequest:
    voice_identity_id: str
    text: str
    language: str
    usage: str
    rate: float
    style: str
    segment_id: str
    correlation_id: str
    schema: str = VOICE_SYNTHESIS_REQUEST_VERSION

    def __post_init__(self) -> None:
        _nonempty(self.voice_identity_id, "voice_identity_id")
        _nonempty(self.text, "text")
        _nonempty(self.language, "language")
        if self.usage not in VOICE_USAGES:
            raise ValueError(f"unsupported voice usage: {self.usage}")
        if not 0.5 <= float(self.rate) <= 2.0:
            raise ValueError("rate must be between 0.5 and 2.0")
        _nonempty(self.segment_id, "segment_id")
        _nonempty(self.correlation_id, "correlation_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VoiceEnrollmentMetrics:
    aggregate_clean_speech_seconds: float
    detected_language: str
    single_speaker: bool
    speech_ratio: float
    silence_ratio: float
    clipping_ratio: float
    peak_dbfs: float
    rms_dbfs: float
    snr_db: float
    transcription_confidence: float
    corrupt_audio: bool


@dataclass(frozen=True)
class VoiceEnrollmentQA:
    status: str
    issues: tuple[str, ...]
    warnings: tuple[str, ...]
    metrics: VoiceEnrollmentMetrics
    schema: str = VOICE_ENROLLMENT_QA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "status": self.status,
            "issues": list(self.issues),
            "warnings": list(self.warnings),
            "metrics": asdict(self.metrics),
        }


def evaluate_voice_enrollment(metrics: VoiceEnrollmentMetrics) -> VoiceEnrollmentQA:
    issues: list[str] = []
    warnings: list[str] = []
    if metrics.corrupt_audio:
        issues.append("CORRUPT_AUDIO")
    if metrics.aggregate_clean_speech_seconds < 30.0:
        issues.append("INSUFFICIENT_CLEAN_SPEECH")
    elif metrics.aggregate_clean_speech_seconds < 60.0:
        warnings.append("BELOW_RECOMMENDED_60_SECONDS")
    if metrics.aggregate_clean_speech_seconds > 0 and metrics.aggregate_clean_speech_seconds < 120.0:
        warnings.append("BELOW_IDEAL_120_SECONDS")
    if str(metrics.detected_language).lower().replace("_", "-") not in {"pt-br", "pt"}:
        issues.append("NON_PTBR_REFERENCE")
    if not metrics.single_speaker:
        issues.append("MULTIPLE_SPEAKERS")
    if not 0.55 <= metrics.speech_ratio <= 1.0:
        issues.append("LOW_SPEECH_RATIO")
    if not 0.0 <= metrics.silence_ratio <= 0.45:
        issues.append("EXCESSIVE_SILENCE")
    if metrics.clipping_ratio > 0.01 or metrics.peak_dbfs > 0.0:
        issues.append("CLIPPING")
    if metrics.rms_dbfs < -40.0:
        issues.append("VERY_LOW_LEVEL")
    if metrics.snr_db < 15.0:
        issues.append("LOW_SNR")
    if metrics.transcription_confidence < 0.80:
        issues.append("LOW_TRANSCRIPTION_CONFIDENCE")
    return VoiceEnrollmentQA(
        status="FAIL" if issues else "PASS",
        issues=tuple(dict.fromkeys(issues)),
        warnings=tuple(dict.fromkeys(warnings)),
        metrics=metrics,
    )


@dataclass(frozen=True)
class VoiceTurnTelemetry:
    turn_id: str
    surface: str
    provider: str
    model: str
    voice_identity_id: str
    stt_latency_ms: float
    harness_latency_ms: float
    tts_latency_ms: float
    total_latency_ms: float
    audio_duration_seconds: float
    interrupted: bool
    task_cancelled: bool
    status: str
    schema: str = VOICE_TURN_TELEMETRY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
