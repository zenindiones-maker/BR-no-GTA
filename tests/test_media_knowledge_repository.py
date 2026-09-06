from __future__ import annotations

from app.database.media_knowledge_repository import (
    MediaKnowledgeRepository,
)
from app.database.schema import initialize_schema
from app.services.media_analysis.models import (
    AudioFeature,
    Beat,
    MediaKnowledge,
    MotionFeature,
    VisualSample,
)


def test_media_knowledge_repository_persists_payload(
    monkeypatch,
    tmp_path,
):
    database_path = tmp_path / "test.sqlite3"

    monkeypatch.setenv(
        "BR_TEST_DATABASE",
        str(database_path),
    )

    initialize_schema()

    knowledge = MediaKnowledge(
        source_path="workspace/test/example.mp4",
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
                time_seconds=0.0,
                path="sample_000000.jpg",
                width=1920,
                height=1080,
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
            "visual_samples_available": True,
            "motion_analysis_available": True,
        },
    )

    repository = MediaKnowledgeRepository()

    knowledge_id = repository.save(knowledge)
    payload = repository.get_payload(knowledge_id)

    assert knowledge_id > 0
    assert payload["source_path"] == knowledge.source_path
    assert payload["audio_features"][0]["rms"] == 0.5
    assert payload["beats"][0]["strength"] == 0.8
    assert payload["visual_samples"][0]["width"] == 1920
    assert payload["motion_features"][0]["motion_score"] == 2.5
    assert payload["metadata"]["analysis_version"] == "3"


def test_media_knowledge_repository_rejects_missing_record(
    monkeypatch,
    tmp_path,
):
    database_path = tmp_path / "test.sqlite3"

    monkeypatch.setenv(
        "BR_TEST_DATABASE",
        str(database_path),
    )

    initialize_schema()

    repository = MediaKnowledgeRepository()

    try:
        repository.get_payload(999999)
    except KeyError as exc:
        assert "999999" in str(exc)
    else:
        raise AssertionError(
            "Era esperado KeyError para MediaKnowledge inexistente."
        )
