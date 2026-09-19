from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.services.media_analysis.audio_analyzer import analyze_audio
from app.services.media_analysis.visual_analyzer import analyze_visual


def analyze_media_technical(
    source_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    sample_interval_seconds: float = 2.0,
) -> dict[str, Any]:
    """Run the bounded technical media analyzers and return serializable evidence."""
    visual_samples, motion_features = analyze_visual(
        source_path,
        output_dir=output_dir,
        sample_interval_seconds=sample_interval_seconds,
    )
    audio_features, beats = analyze_audio(source_path)
    return {
        "source_path": str(Path(source_path)),
        "visual_samples": [asdict(item) for item in visual_samples],
        "motion_features": [asdict(item) for item in motion_features],
        "audio_features": [asdict(item) for item in audio_features],
        "beats": [asdict(item) for item in beats],
    }
