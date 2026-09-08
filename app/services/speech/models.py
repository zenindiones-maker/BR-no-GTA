from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SPEECH_ANALYSIS_VERSION = "1"


@dataclass(frozen=True)
class SpeechWord:
    text: str
    start_seconds: float
    end_seconds: float
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SpeechSegment:
    segment_id: str
    start_seconds: float
    end_seconds: float
    text: str
    speaker_id: str | None = None
    words: tuple[SpeechWord, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "text": self.text,
            "speaker_id": self.speaker_id,
            "words": [word.to_dict() for word in self.words],
        }


@dataclass(frozen=True)
class SpeechSpeaker:
    speaker_id: str
    label: str | None = None
    segments: tuple[str, ...] = ()
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "speaker_id": self.speaker_id,
            "label": self.label,
            "segments": list(self.segments),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class SpeechQuality:
    transcription_confidence: float
    timestamp_confidence: float
    speaker_confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SpeechEngine:
    provider: str
    model: str
    version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SpeechAnalysis:
    source_path: str
    duration_seconds: float
    source_language: str
    language_probability: float
    analysis_version: str = SPEECH_ANALYSIS_VERSION
    segments: tuple[SpeechSegment, ...] = ()
    speakers: tuple[SpeechSpeaker, ...] = ()
    speech_seconds: float = 0.0
    words_per_minute: float = 0.0
    quality: SpeechQuality = field(
        default_factory=lambda: SpeechQuality(
            transcription_confidence=0.0,
            timestamp_confidence=0.0,
            speaker_confidence=None,
        )
    )
    engine: SpeechEngine = field(
        default_factory=lambda: SpeechEngine(
            provider="unknown",
            model="unknown",
            version=None,
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_version": self.analysis_version,
            "source_path": self.source_path,
            "duration_seconds": self.duration_seconds,
            "source_language": self.source_language,
            "language_probability": self.language_probability,
            "segments": [
                segment.to_dict()
                for segment in self.segments
            ],
            "speakers": [
                speaker.to_dict()
                for speaker in self.speakers
            ],
            "speech_seconds": self.speech_seconds,
            "words_per_minute": self.words_per_minute,
            "quality": self.quality.to_dict(),
            "engine": self.engine.to_dict(),
        }
