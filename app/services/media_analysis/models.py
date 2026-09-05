from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MediaStream:
    index: int
    codec_type: str
    codec_name: str | None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    sample_rate: int | None = None
    channels: int | None = None


@dataclass(frozen=True)
class MediaProbe:
    format_name: str | None
    duration_seconds: float | None
    size_bytes: int | None
    streams: tuple[MediaStream, ...]


@dataclass(frozen=True)
class SceneBoundary:
    start_seconds: float
    end_seconds: float
    score: float | None = None

@dataclass(frozen=True)
class SceneKnowledge:
    index: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    detection_method: str


@dataclass(frozen=True)
class TranscriptWord:
    word: str
    start_seconds: float
    end_seconds: float
    confidence: float | None = None


@dataclass(frozen=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str
    words: tuple[TranscriptWord, ...] = ()


@dataclass(frozen=True)
class AudioFeature:
    start_seconds: float
    end_seconds: float
    rms: float | None = None
    peak: float | None = None
    silence: bool = False


@dataclass(frozen=True)
class Beat:
    time_seconds: float
    strength: float | None = None


@dataclass(frozen=True)
class VisualSample:
    time_seconds: float
    path: str
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class MediaKnowledge:
    source_path: str
    probe: MediaProbe | None = None
    scenes: tuple[SceneKnowledge, ...] = ()
    transcript: tuple[TranscriptSegment, ...] = ()
    audio_features: tuple[AudioFeature, ...] = ()
    beats: tuple[Beat, ...] = ()
    visual_samples: tuple[VisualSample, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
