from __future__ import annotations

import math
from dataclasses import dataclass

from app.services.speech.models import SpeechAnalysis, SPEECH_ANALYSIS_VERSION


@dataclass(frozen=True)
class SpeechQAResult:
    passed: bool
    issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "issues": list(self.issues),
            "warnings": list(self.warnings),
        }


def _finite(value: float) -> bool:
    return math.isfinite(value)


def _confidence_valid(value: float | None) -> bool:
    return value is None or (
        _finite(value) and 0.0 <= value <= 1.0
    )


def validate_speech_analysis(
    analysis: SpeechAnalysis,
) -> SpeechQAResult:
    issues: list[str] = []
    warnings: list[str] = []

    # ============================================================
    # IDENTIDADE / CONTRATO
    # ============================================================

    if not isinstance(analysis.analysis_version, str):
        issues.append("INVALID_ANALYSIS_VERSION")
    elif analysis.analysis_version != SPEECH_ANALYSIS_VERSION:
        issues.append("INVALID_ANALYSIS_VERSION")

    if not isinstance(analysis.source_path, str):
        issues.append("SPEECH_SOURCE_PATH_INVALID")
    elif not analysis.source_path.strip():
        issues.append("SPEECH_SOURCE_PATH_EMPTY")

    # ============================================================
    # DURAÇÃO / MÉTRICAS GLOBAIS
    # ============================================================

    if (
        not _finite(analysis.duration_seconds)
        or analysis.duration_seconds <= 0
    ):
        issues.append("SPEECH_INVALID_DURATION")

    if not _finite(analysis.language_probability):
        issues.append("SPEECH_INVALID_LANGUAGE_PROBABILITY")
    elif not 0.0 <= analysis.language_probability <= 1.0:
        issues.append("SPEECH_INVALID_LANGUAGE_PROBABILITY")

    if not isinstance(analysis.source_language, str):
        issues.append("LANGUAGE_DETECTION_FAILED")
    elif not analysis.source_language.strip():
        issues.append("LANGUAGE_DETECTION_FAILED")

    if not _finite(analysis.speech_seconds):
        issues.append("SPEECH_INVALID_SPEECH_DURATION")
    elif analysis.speech_seconds < 0:
        issues.append("SPEECH_INVALID_SPEECH_DURATION")

    if (
        _finite(analysis.duration_seconds)
        and _finite(analysis.speech_seconds)
        and analysis.speech_seconds > analysis.duration_seconds + 0.25
    ):
        issues.append("SPEECH_DURATION_EXCEEDED")

    if not _finite(analysis.words_per_minute):
        issues.append("SPEECH_INVALID_WPM")
    elif analysis.words_per_minute < 0:
        issues.append("SPEECH_INVALID_WPM")

    # ============================================================
    # QUALITY
    # ============================================================

    quality = analysis.quality

    if not _confidence_valid(quality.transcription_confidence):
        issues.append("SPEECH_INVALID_TRANSCRIPTION_CONFIDENCE")

    if not _confidence_valid(quality.timestamp_confidence):
        issues.append("SPEECH_INVALID_TIMESTAMP_CONFIDENCE")

    if not _confidence_valid(quality.speaker_confidence):
        issues.append("SPEECH_INVALID_SPEAKER_CONFIDENCE")

    # ============================================================
    # ENGINE / PROVENANCE
    # ============================================================

    engine = analysis.engine

    if not isinstance(engine.provider, str) or not engine.provider.strip():
        issues.append("SPEECH_ENGINE_PROVIDER_EMPTY")

    if not isinstance(engine.model, str) or not engine.model.strip():
        issues.append("SPEECH_ENGINE_MODEL_EMPTY")

    if engine.version is not None:
        if not isinstance(engine.version, str) or not engine.version.strip():
            issues.append("SPEECH_ENGINE_VERSION_INVALID")

    # ============================================================
    # SEGMENTS
    # ============================================================

    if not analysis.segments:
        issues.append("SPEECH_EMPTY")

    segment_ids: set[str] = set()
    speaker_segment_map: dict[str, list[str]] = {}

    for segment in analysis.segments:
        if not segment.segment_id.strip():
            issues.append("EMPTY_SEGMENT_ID")
        elif segment.segment_id in segment_ids:
            issues.append("DUPLICATE_SEGMENT_ID")
        else:
            segment_ids.add(segment.segment_id)

        if not segment.text.strip():
            issues.append("EMPTY_SEGMENT_TEXT")

        if (
            not _finite(segment.start_seconds)
            or not _finite(segment.end_seconds)
        ):
            issues.append("INVALID_TIMESTAMPS")
            continue

        if segment.start_seconds < 0:
            issues.append("INVALID_TIMESTAMPS")

        if segment.end_seconds <= segment.start_seconds:
            issues.append("INVALID_TIMESTAMPS")

        if (
            _finite(analysis.duration_seconds)
            and segment.end_seconds
            > analysis.duration_seconds + 0.25
        ):
            issues.append("INVALID_TIMESTAMPS")

        if segment.speaker_id is not None:
            if not segment.speaker_id.strip():
                issues.append("INVALID_SPEAKER_REFERENCE")
            else:
                speaker_segment_map.setdefault(
                    segment.speaker_id,
                    [],
                ).append(segment.segment_id)

        # ========================================================
        # WORDS
        # ========================================================

        previous_word_end = segment.start_seconds

        for word in segment.words:
            if not word.text.strip():
                issues.append("EMPTY_WORD_TEXT")

            if (
                not _finite(word.start_seconds)
                or not _finite(word.end_seconds)
            ):
                issues.append("INVALID_WORD_TIMESTAMPS")
                continue

            if word.start_seconds < segment.start_seconds - 0.25:
                issues.append("INVALID_WORD_TIMESTAMPS")

            if word.end_seconds <= word.start_seconds:
                issues.append("INVALID_WORD_TIMESTAMPS")

            if word.end_seconds > segment.end_seconds + 0.25:
                issues.append("INVALID_WORD_TIMESTAMPS")

            if word.start_seconds < previous_word_end - 0.001:
                issues.append("INVALID_WORD_TIMESTAMPS")

            if not _confidence_valid(word.confidence):
                issues.append("INVALID_WORD_CONFIDENCE")

            previous_word_end = max(
                previous_word_end,
                word.end_seconds,
            )

    # ============================================================
    # SEGMENT OVERLAP
    #
    # Overlap é permitido somente entre speakers diferentes.
    # ============================================================

    ordered_segments = sorted(
        analysis.segments,
        key=lambda item: (
            item.start_seconds,
            item.end_seconds,
            item.segment_id,
        ),
    )

    for index, current in enumerate(ordered_segments):
        for previous in ordered_segments[:index]:
            if previous.end_seconds <= current.start_seconds + 0.001:
                continue

            if (
                previous.speaker_id is None
                or current.speaker_id is None
                or previous.speaker_id == current.speaker_id
            ):
                issues.append("INVALID_TIMESTAMPS")
                break

    # ============================================================
    # SPEAKERS / DIARIZATION CONSISTENCY
    # ============================================================

    speaker_ids: set[str] = set()

    for speaker in analysis.speakers:
        if not speaker.speaker_id.strip():
            issues.append("EMPTY_SPEAKER_ID")
            continue

        if speaker.speaker_id in speaker_ids:
            issues.append("DUPLICATE_SPEAKER_ID")

        speaker_ids.add(speaker.speaker_id)

        if not _confidence_valid(speaker.confidence):
            issues.append("INVALID_SPEAKER_CONFIDENCE")

        declared_segments = set(speaker.segments)

        for segment_id in declared_segments:
            if segment_id not in segment_ids:
                issues.append("SPEAKER_REFERENCES_UNKNOWN_SEGMENT")

        actual_segments = set(
            speaker_segment_map.get(speaker.speaker_id, [])
        )

        if declared_segments != actual_segments:
            issues.append("INCONSISTENT_SPEAKER_SEGMENTS")

    # Todo speaker usado por segmento precisa existir na lista de speakers.
    for speaker_id in speaker_segment_map:
        if speaker_id not in speaker_ids:
            issues.append("UNKNOWN_SPEAKER_REFERENCE")

    # Se há speakers, todos os segmentos diarizados precisam estar
    # representados de forma consistente.
    if analysis.speakers:
        for segment in analysis.segments:
            if segment.speaker_id is not None:
                if segment.speaker_id not in speaker_ids:
                    issues.append("UNKNOWN_SPEAKER_REFERENCE")

    # ============================================================
    # RESULTADO
    # ============================================================

    return SpeechQAResult(
        passed=not issues,
        issues=tuple(dict.fromkeys(issues)),
        warnings=tuple(dict.fromkeys(warnings)),
    )
