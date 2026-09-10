from __future__ import annotations

from app.services.media_analysis.models import (
    AudioFeature,
    Beat,
    MediaKnowledge,
    MediaProbe,
    MediaStream,
    MotionFeature,
    SceneKnowledge,
    TranscriptSegment,
    TranscriptWord,
    VisualSample,
)
from app.services.media_analysis.serialization import (
    deserialize_media_knowledge,
    serialize_media_knowledge,
)


def test_media_knowledge_round_trip():
    knowledge = MediaKnowledge(
        source_path="remote://media-worker/trailer-2",
        probe=MediaProbe(
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
            duration_seconds=120.5,
            size_bytes=123456,
            streams=(
                MediaStream(
                    index=0,
                    codec_type="video",
                    codec_name="h264",
                    width=1920,
                    height=1080,
                    fps=30.0,
                ),
            ),
        ),
        scenes=(
            SceneKnowledge(
                index=1,
                start_seconds=0.0,
                end_seconds=10.0,
                duration_seconds=10.0,
                detection_method="pyscenedetect",
            ),
        ),
        transcript=(
            TranscriptSegment(
                start_seconds=1.0,
                end_seconds=3.0,
                text="Grand Theft Auto VI",
                words=(
                    TranscriptWord(
                        word="Grand",
                        start_seconds=1.0,
                        end_seconds=1.5,
                        confidence=0.99,
                    ),
                ),
            ),
        ),
        audio_features=(
            AudioFeature(
                start_seconds=0.0,
                end_seconds=1.0,
                rms=0.5,
                peak=0.9,
                silence=False,
            ),
        ),
        beats=(
            Beat(
                time_seconds=0.5,
                strength=0.8,
            ),
        ),
        visual_samples=(
            VisualSample(
                time_seconds=2.5,
                path=None,
                width=1920,
                height=1080,
                frame_ref="frame:2.500",
            ),
        ),
        motion_features=(
            MotionFeature(
                start_seconds=0.0,
                end_seconds=1.0,
                motion_score=2.5,
            ),
        ),
        metadata={
            "analysis_version": "3",
            "source_storage": "remote",
            "source_local_file_required": False,
        },
    )

    payload = serialize_media_knowledge(knowledge)
    restored = deserialize_media_knowledge(payload)

    assert restored == knowledge


def test_media_knowledge_deserializes_remote_visual_sample():
    payload = {
        "source_path": "remote://media-worker/trailer-2",
        "visual_samples": [
            {
                "time_seconds": 7.125,
                "path": None,
                "width": 1920,
                "height": 1080,
                "frame_ref": "frame:7.125",
            },
        ],
        "metadata": {
            "source_storage": "remote",
            "source_local_file_required": False,
        },
    }

    knowledge = deserialize_media_knowledge(payload)

    assert len(knowledge.visual_samples) == 1
    assert knowledge.visual_samples[0].path is None
    assert knowledge.visual_samples[0].frame_ref == "frame:7.125"
    assert knowledge.source_path == "remote://media-worker/trailer-2"
