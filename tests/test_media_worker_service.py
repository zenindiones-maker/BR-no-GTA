from __future__ import annotations

from pathlib import Path

from app.database.schema import initialize_schema
from app.database.media_knowledge_repository import MediaKnowledgeRepository
from app.services.media_analysis.models import MediaKnowledge
from app.services.media_worker_service import run_media_analysis


def test_media_worker_persists_media_knowledge(
    monkeypatch,
    tmp_path,
):
    database_path = tmp_path / "worker.sqlite3"
    source = tmp_path / "example.mp4"
    source.write_bytes(b"fake-media")

    monkeypatch.setenv(
        "BR_TEST_DATABASE",
        str(database_path),
    )

    initialize_schema()

    knowledge = MediaKnowledge(
        source_path=str(source),
        metadata={
            "analysis_version": "3",
        },
    )

    monkeypatch.setattr(
        "app.services.media_worker_service.analyze_media",
        lambda path: knowledge,
    )

    result = run_media_analysis(source)

    assert result.knowledge_id > 0
    assert result.knowledge.source_path == str(source)

    payload = MediaKnowledgeRepository().get_payload(
        result.knowledge_id,
    )

    assert payload["source_path"] == str(source)
    assert payload["metadata"]["analysis_version"] == "3"


def test_media_worker_returns_analysis_result(
    monkeypatch,
    tmp_path,
):
    database_path = tmp_path / "worker.sqlite3"
    source = tmp_path / "example.mp4"
    source.write_bytes(b"fake-media")

    monkeypatch.setenv(
        "BR_TEST_DATABASE",
        str(database_path),
    )

    initialize_schema()

    knowledge = MediaKnowledge(
        source_path=str(source),
    )

    monkeypatch.setattr(
        "app.services.media_worker_service.analyze_media",
        lambda path: knowledge,
    )

    result = run_media_analysis(source)

    assert result.knowledge == knowledge
    assert result.knowledge_id > 0
