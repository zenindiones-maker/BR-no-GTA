from __future__ import annotations

from app.database.media_knowledge_repository import (
    MediaKnowledgeRepository,
)
from app.database.schema import initialize_schema
from app.database.speech_analysis_repository import (
    SpeechAnalysisRepository,
)
from app.services.media_analysis.models import MediaKnowledge
from app.services.speech.models import (
    SpeechAnalysis,
    SpeechEngine,
    SpeechQuality,
    SpeechSegment,
    SpeechSpeaker,
    SpeechWord,
)


def _create_media_knowledge() -> int:
    repository = MediaKnowledgeRepository()

    return repository.save(
        MediaKnowledge(
            source_path="workspace/test/example.mp4",
            metadata={"analysis_version": "3"},
        )
    )


def _create_analysis() -> SpeechAnalysis:
    return SpeechAnalysis(
        source_path="workspace/test/example.mp4",
        duration_seconds=12.5,
        source_language="en",
        language_probability=0.99,
        segments=(
            SpeechSegment(
                segment_id="seg-001",
                start_seconds=1.0,
                end_seconds=3.5,
                text="This is GTA 6.",
                speaker_id="speaker-01",
                words=(
                    SpeechWord(
                        text="This",
                        start_seconds=1.0,
                        end_seconds=1.3,
                        confidence=0.98,
                    ),
                    SpeechWord(
                        text="is",
                        start_seconds=1.31,
                        end_seconds=1.5,
                        confidence=0.99,
                    ),
                    SpeechWord(
                        text="GTA",
                        start_seconds=1.51,
                        end_seconds=2.0,
                        confidence=0.97,
                    ),
                    SpeechWord(
                        text="6.",
                        start_seconds=2.01,
                        end_seconds=2.4,
                        confidence=0.96,
                    ),
                ),
            ),
        ),
        speakers=(
            SpeechSpeaker(
                speaker_id="speaker-01",
                label="Narrator",
                segments=("seg-001",),
                confidence=0.95,
            ),
        ),
        speech_seconds=2.5,
        words_per_minute=96.0,
        quality=SpeechQuality(
            transcription_confidence=0.97,
            timestamp_confidence=0.96,
            speaker_confidence=0.95,
        ),
        engine=SpeechEngine(
            provider="test-provider",
            model="test-model",
            version="1.0",
        ),
    )


def test_speech_analysis_repository_persists_full_payload(
    monkeypatch,
    tmp_path,
):
    database_path = tmp_path / "test.sqlite3"

    monkeypatch.setenv(
        "BR_TEST_DATABASE",
        str(database_path),
    )

    initialize_schema()

    media_knowledge_id = _create_media_knowledge()
    analysis = _create_analysis()

    repository = SpeechAnalysisRepository()

    analysis_id = repository.save(
        media_knowledge_id=media_knowledge_id,
        analysis=analysis,
    )

    payload = repository.get_payload(analysis_id)

    assert analysis_id > 0
    assert payload["analysis_version"] == "1"
    assert payload["analysis_version"] != payload["engine"]["version"]
    assert payload["source_path"] == analysis.source_path
    assert payload["source_language"] == "en"
    assert payload["language_probability"] == 0.99

    assert payload["segments"][0]["segment_id"] == "seg-001"
    assert payload["segments"][0]["speaker_id"] == "speaker-01"
    assert payload["segments"][0]["words"][2]["text"] == "GTA"
    assert payload["segments"][0]["words"][2]["start_seconds"] == 1.51

    assert payload["speakers"][0]["speaker_id"] == "speaker-01"
    assert payload["quality"]["transcription_confidence"] == 0.97
    assert payload["engine"]["provider"] == "test-provider"
    assert payload["engine"]["model"] == "test-model"


def test_speech_analysis_repository_lists_by_media_knowledge(
    monkeypatch,
    tmp_path,
):
    database_path = tmp_path / "test.sqlite3"

    monkeypatch.setenv(
        "BR_TEST_DATABASE",
        str(database_path),
    )

    initialize_schema()

    media_knowledge_id = _create_media_knowledge()
    analysis = _create_analysis()

    repository = SpeechAnalysisRepository()

    first_id = repository.save(
        media_knowledge_id=media_knowledge_id,
        analysis=analysis,
    )

    second_id = repository.save(
        media_knowledge_id=media_knowledge_id,
        analysis=analysis,
    )

    rows = repository.get_by_media_knowledge(
        media_knowledge_id,
    )

    assert [row["id"] for row in rows] == [
        first_id,
        second_id,
    ]
    assert all(
        row["media_knowledge_id"] == media_knowledge_id
        for row in rows
    )
    assert all(
        row["provider"] == "test-provider"
        for row in rows
    )


def test_speech_analysis_repository_rejects_missing_record(
    monkeypatch,
    tmp_path,
):
    database_path = tmp_path / "test.sqlite3"

    monkeypatch.setenv(
        "BR_TEST_DATABASE",
        str(database_path),
    )

    initialize_schema()

    repository = SpeechAnalysisRepository()

    try:
        repository.get_payload(999999)
    except KeyError as exc:
        assert "999999" in str(exc)
    else:
        raise AssertionError(
            "Era esperado KeyError para SpeechAnalysis inexistente."
        )


def test_speech_analysis_requires_existing_media_knowledge(
    monkeypatch,
    tmp_path,
):
    database_path = tmp_path / "test.sqlite3"

    monkeypatch.setenv(
        "BR_TEST_DATABASE",
        str(database_path),
    )

    initialize_schema()

    repository = SpeechAnalysisRepository()

    try:
        repository.save(
            media_knowledge_id=999999,
            analysis=_create_analysis(),
        )
    except KeyError as exc:
        assert "MediaKnowledge não encontrado: 999999" in str(exc)
    else:
        raise AssertionError(
            "Era esperado KeyError para MediaKnowledge inexistente."
        )

def test_speech_analysis_rejects_source_path_mismatch(
    monkeypatch,
    tmp_path,
):
    database_path = tmp_path / "test.sqlite3"

    monkeypatch.setenv(
        "BR_TEST_DATABASE",
        str(database_path),
    )

    initialize_schema()

    media_knowledge_id = _create_media_knowledge()

    analysis = _create_analysis()
    mismatched_analysis = SpeechAnalysis(
        source_path="workspace/test/different.mp4",
        duration_seconds=analysis.duration_seconds,
        source_language=analysis.source_language,
        language_probability=analysis.language_probability,
        analysis_version=analysis.analysis_version,
        segments=analysis.segments,
        speakers=analysis.speakers,
        speech_seconds=analysis.speech_seconds,
        words_per_minute=analysis.words_per_minute,
        quality=analysis.quality,
        engine=analysis.engine,
    )

    repository = SpeechAnalysisRepository()

    try:
        repository.save(
            media_knowledge_id=media_knowledge_id,
            analysis=mismatched_analysis,
        )
    except ValueError as exc:
        message = str(exc)
        assert "source_path" in message
        assert "different.mp4" in message
        assert "example.mp4" in message
    else:
        raise AssertionError(
            "Era esperado ValueError para source_path incompatível."
        )

    rows = repository.get_by_media_knowledge(
        media_knowledge_id,
    )

    assert rows == []
