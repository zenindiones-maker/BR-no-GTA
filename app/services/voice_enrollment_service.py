from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.services.voice_plane_contracts import ConsentStatus


VOICE_REFERENCE_SUITABILITIES = frozenset({
    "VOICE_IDENTITY_REFERENCE",
    "PRONUNCIATION_REFERENCE",
    "AUDITION_ONLY",
    "REJECT",
})


def _sha256(value: str, field: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"{field} must be a sha256 hex digest")
    return digest


def _private_ref(value: str, field: str) -> str:
    ref = str(value or "").strip()
    if not ref.startswith("private://"):
        raise ValueError(f"{field} must use private:// storage")
    return ref


@dataclass(frozen=True)
class VoiceReferenceMetrics:
    duration_seconds: float
    clean_speech_seconds: float
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
    heavy_music_detected: bool
    critical_pronunciation_term_count: int = 0

    def __post_init__(self) -> None:
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if not 0 <= self.clean_speech_seconds <= self.duration_seconds:
            raise ValueError("clean_speech_seconds must be within duration")
        for field_name in ("speech_ratio", "silence_ratio", "clipping_ratio", "transcription_confidence"):
            value = float(getattr(self, field_name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0 and 1")
        if self.critical_pronunciation_term_count < 0:
            raise ValueError("critical_pronunciation_term_count cannot be negative")


@dataclass(frozen=True)
class VoiceReferenceRecord:
    reference_id: str
    private_audio_ref: str
    audio_sha256: str
    private_transcript_ref: str
    transcript_sha256: str
    metrics: VoiceReferenceMetrics

    def __post_init__(self) -> None:
        if not str(self.reference_id or "").strip():
            raise ValueError("reference_id is required")
        _private_ref(self.private_audio_ref, "private_audio_ref")
        _private_ref(self.private_transcript_ref, "private_transcript_ref")
        _sha256(self.audio_sha256, "audio_sha256")
        _sha256(self.transcript_sha256, "transcript_sha256")


@dataclass(frozen=True)
class VoiceReferenceAssessment:
    reference_id: str
    private_audio_ref: str
    audio_sha256: str
    private_transcript_ref: str
    transcript_sha256: str
    metrics: VoiceReferenceMetrics
    suitability: str
    issues: tuple[str, ...]
    quality_score: float

    def __post_init__(self) -> None:
        if self.suitability not in VOICE_REFERENCE_SUITABILITIES:
            raise ValueError("invalid voice reference suitability")


@dataclass(frozen=True)
class OwnerVoiceEnrollmentDecision:
    voice_identity_id: str
    consent_status: str
    status: str
    aggregate_clean_speech_seconds: float
    primary_reference_id: str | None
    accepted_reference_ids: tuple[str, ...]
    issues: tuple[str, ...]


def _is_ptbr(language: str) -> bool:
    return str(language or "").strip().lower().replace("_", "-") in {"pt", "pt-br"}


def _quality_score(metrics: VoiceReferenceMetrics) -> float:
    # Quality dominates duration. Clean-speech duration contributes only a
    # bounded 5-point term so a long noisy clip never wins by length alone.
    confidence = min(max(float(metrics.transcription_confidence), 0.0), 1.0) * 40.0
    snr = min(max(float(metrics.snr_db), 0.0), 35.0) / 35.0 * 30.0
    clipping = (1.0 - min(max(float(metrics.clipping_ratio), 0.0) / 0.01, 1.0)) * 20.0
    speech = min(max(float(metrics.speech_ratio), 0.0), 1.0) * 5.0
    duration = min(max(float(metrics.clean_speech_seconds), 0.0), 30.0) / 30.0 * 5.0
    return round(confidence + snr + clipping + speech + duration, 6)


def assess_voice_reference(record: VoiceReferenceRecord) -> VoiceReferenceAssessment:
    m = record.metrics
    hard_issues: list[str] = []
    soft_issues: list[str] = []

    if m.corrupt_audio:
        hard_issues.append("CORRUPT_AUDIO")
    if m.heavy_music_detected:
        hard_issues.append("HEAVY_MUSIC")
    if not m.single_speaker:
        hard_issues.append("MULTIPLE_SPEAKERS")
    if not _is_ptbr(m.detected_language):
        hard_issues.append("NON_PTBR_REFERENCE")
    if m.clipping_ratio > 0.02 or m.peak_dbfs > 0.0:
        hard_issues.append("SEVERE_CLIPPING")
    if m.snr_db < 12.0:
        hard_issues.append("LOW_SNR")
    if m.transcription_confidence < 0.72:
        hard_issues.append("LOW_TRANSCRIPTION_CONFIDENCE")
    if m.speech_ratio < 0.45:
        hard_issues.append("LOW_SPEECH_RATIO")
    if m.silence_ratio > 0.55:
        hard_issues.append("EXCESSIVE_SILENCE")

    if hard_issues:
        suitability = "REJECT"
    else:
        identity_grade = bool(
            m.clean_speech_seconds >= 12.0
            and m.transcription_confidence >= 0.90
            and m.snr_db >= 18.0
            and m.clipping_ratio <= 0.01
            and m.speech_ratio >= 0.60
            and m.silence_ratio <= 0.40
        )
        if identity_grade:
            suitability = "VOICE_IDENTITY_REFERENCE"
        elif (
            m.critical_pronunciation_term_count > 0
            and m.transcription_confidence >= 0.80
            and m.snr_db >= 15.0
        ):
            suitability = "PRONUNCIATION_REFERENCE"
        else:
            suitability = "AUDITION_ONLY"

        if m.clipping_ratio > 0:
            soft_issues.append("MINOR_CLIPPING")
        if m.snr_db < 20.0:
            soft_issues.append("MODERATE_NOISE")
        if m.transcription_confidence < 0.90:
            soft_issues.append("MODERATE_TRANSCRIPTION_CONFIDENCE")

    return VoiceReferenceAssessment(
        reference_id=record.reference_id,
        private_audio_ref=record.private_audio_ref,
        audio_sha256=_sha256(record.audio_sha256, "audio_sha256"),
        private_transcript_ref=record.private_transcript_ref,
        transcript_sha256=_sha256(record.transcript_sha256, "transcript_sha256"),
        metrics=m,
        suitability=suitability,
        issues=tuple(dict.fromkeys((*hard_issues, *soft_issues))),
        quality_score=_quality_score(m),
    )


def select_primary_voice_reference(
    assessments: Iterable[VoiceReferenceAssessment],
) -> VoiceReferenceAssessment:
    eligible = [
        item
        for item in assessments
        if item.suitability == "VOICE_IDENTITY_REFERENCE"
    ]
    if not eligible:
        raise RuntimeError("VOICE_REFERENCE_QA_FAILED")
    # Highest quality first. SHA is a stable final tie-break independent of
    # input order and filename/reference naming.
    return sorted(
        eligible,
        key=lambda item: (-item.quality_score, item.audio_sha256, item.reference_id),
    )[0]


def evaluate_owner_enrollment(
    *,
    voice_identity_id: str,
    consent: ConsentStatus,
    assessments: Iterable[VoiceReferenceAssessment],
) -> OwnerVoiceEnrollmentDecision:
    values = tuple(assessments)
    accepted = tuple(item for item in values if item.suitability != "REJECT")
    aggregate = round(
        sum(item.metrics.clean_speech_seconds for item in accepted),
        6,
    )
    issues: list[str] = []

    if consent is not ConsentStatus.APPROVED:
        return OwnerVoiceEnrollmentDecision(
            voice_identity_id=voice_identity_id,
            consent_status=consent.value,
            status="CONSENT_REQUIRED",
            aggregate_clean_speech_seconds=aggregate,
            primary_reference_id=None,
            accepted_reference_ids=tuple(item.reference_id for item in accepted),
            issues=("CONSENT_NOT_APPROVED",),
        )

    identity_refs = tuple(
        item for item in accepted
        if item.suitability == "VOICE_IDENTITY_REFERENCE"
    )
    if aggregate < 30.0:
        issues.append("INSUFFICIENT_AGGREGATE_CLEAN_SPEECH")
    if not identity_refs:
        issues.append("NO_IDENTITY_GRADE_REFERENCE")

    if issues:
        return OwnerVoiceEnrollmentDecision(
            voice_identity_id=voice_identity_id,
            consent_status=consent.value,
            status="VOICE_REFERENCE_QA_FAILED",
            aggregate_clean_speech_seconds=aggregate,
            primary_reference_id=None,
            accepted_reference_ids=tuple(item.reference_id for item in accepted),
            issues=tuple(issues),
        )

    primary = select_primary_voice_reference(identity_refs)
    return OwnerVoiceEnrollmentDecision(
        voice_identity_id=voice_identity_id,
        consent_status=consent.value,
        status="READY_FOR_PRIVATE_PROMPT_PREPARATION",
        aggregate_clean_speech_seconds=aggregate,
        primary_reference_id=primary.reference_id,
        accepted_reference_ids=tuple(item.reference_id for item in accepted),
        issues=(),
    )
