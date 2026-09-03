from app.database.schema import initialize_schema
from app.database.ideas_repository import insert_idea
from app.database.scripts_repository import insert_script
from app.database.content_unit_repository import insert_content_unit
from app.database.content_segment_repository import insert_content_segment
from app.database.episode_repository import (
    get_episode,
    list_episodes,
    update_episode_status,
)
from app.database.episode_segment_repository import (
    get_episode_segment,
    list_episode_segments,
    update_episode_segment_status,
)
from app.services.content_item_service import create_content_item
from app.services.episode_service import (
    EpisodeError,
    create_and_persist_episode,
)
from app.services.episode_segment_service import (
    EpisodeSegmentError,
    create_and_persist_episode_segment,
)


def _create_content_segment() -> int:
    idea_id = insert_idea(
        title="Ideia GTA 6",
        description="Conteúdo de teste.",
    )

    script_id = insert_script(
        idea_id=idea_id,
        title="Script GTA 6",
        content="Roteiro de teste.",
    )

    content_item = create_content_item(
        {
            "script_id": script_id,
            "idea_id": idea_id,
            "objective": "Gerar um conteúdo curto.",
            "audience": "Público GTA 6.",
            "estimated_duration_seconds": 60.0,
            "format": "short",
            "tone": "informativo",
            "hook": "Novo detalhe de GTA 6.",
            "narrative_blocks": [
                "Bloco narrativo de teste.",
            ],
            "facts_sources": [
                "Fonte de teste.",
            ],
            "cta": "Acompanhe o BR no GTA.",
            "visual_requirements": [
                {
                    "type": "gameplay",
                    "description": "Gameplay de GTA 6.",
                },
            ],
        }
    )

    content_item_id = content_item["id"]

    unit_id = insert_content_unit(
        content_item_id=content_item_id,
        title="Content Unit GTA 6",
        unit_type="short",
        duration_seconds=60.0,
        media_format="portrait_9_16",
        script_id=script_id,
        idea_id=idea_id,
        objective="Gerar um conteúdo curto.",
        hook="Novo detalhe de GTA 6.",
        narration="Narração de teste.",
        visual_requirements=[],
        status="ready",
        file_path=None,
    )

    segment_id = insert_content_segment(
        content_unit_id=unit_id,
        segment_order=0,
        duration_seconds=30.0,
        media_format="portrait_9_16",
        source_start_seconds=0.0,
        source_end_seconds=30.0,
        role="content",
        status="ready",
        file_path=None,
    )

    return segment_id


def test_create_and_persist_episode():
    initialize_schema()

    episode = create_and_persist_episode(
        title="GTA 6 — Episódio 001",
    )

    assert episode["id"] > 0
    assert episode["title"] == "GTA 6 — Episódio 001"
    assert episode["target_duration_seconds"] == 900.0
    assert episode["min_duration_seconds"] == 840.0
    assert episode["max_duration_seconds"] == 960.0
    assert episode["status"] == "draft"

    persisted = get_episode(episode["id"])

    assert persisted is not None
    assert persisted["id"] == episode["id"]
    assert persisted["title"] == episode["title"]


def test_create_and_persist_episode_normalizes_domain_values():
    initialize_schema()

    episode = create_and_persist_episode(
        title="  GTA 6 — Episódio 002  ",
        status="  ready  ",
    )

    assert episode["title"] == "GTA 6 — Episódio 002"
    assert episode["status"] == "ready"


def test_create_and_persist_episode_rejects_invalid_duration():
    initialize_schema()

    try:
        create_and_persist_episode(
            title="Episódio inválido",
            target_duration_seconds=1000.0,
            min_duration_seconds=840.0,
            max_duration_seconds=960.0,
        )
    except EpisodeError:
        pass
    else:
        raise AssertionError(
            "EpisodeError era esperado."
        )


def test_create_and_persist_episode_can_be_listed_and_updated():
    initialize_schema()

    episode = create_and_persist_episode(
        title="Episódio para fila",
    )

    episodes = list_episodes()

    assert any(
        item["id"] == episode["id"]
        for item in episodes
    )

    updated = update_episode_status(
        episode["id"],
        "ready",
    )

    assert updated is True

    persisted = get_episode(episode["id"])

    assert persisted is not None
    assert persisted["status"] == "ready"


def test_create_and_persist_episode_segment():
    initialize_schema()

    segment_id = _create_content_segment()

    episode = create_and_persist_episode(
        title="GTA 6 — Episódio 003",
    )

    episode_segment = create_and_persist_episode_segment(
        episode_id=episode["id"],
        content_segment_id=segment_id,
        order=0,
        start_offset_seconds=0.0,
        role="content",
    )

    assert episode_segment["id"] > 0
    assert episode_segment["episode_id"] == episode["id"]
    assert (
        episode_segment["content_segment_id"]
        == segment_id
    )
    assert episode_segment["segment_order"] == 0
    assert episode_segment["start_offset_seconds"] == 0.0
    assert episode_segment["role"] == "content"
    assert episode_segment["status"] == "ready"

    persisted = get_episode_segment(
        episode_segment["id"]
    )

    assert persisted is not None
    assert persisted["id"] == episode_segment["id"]


def test_create_and_persist_episode_segment_normalizes_values():
    initialize_schema()

    segment_id = _create_content_segment()

    episode = create_and_persist_episode(
        title="Episódio normalização",
    )

    episode_segment = create_and_persist_episode_segment(
        episode_id=episode["id"],
        content_segment_id=segment_id,
        order=1,
        role="  content  ",
    )

    assert episode_segment["role"] == "content"


def test_create_and_persist_episode_segment_rejects_invalid_ids():
    initialize_schema()

    try:
        create_and_persist_episode_segment(
            episode_id=0,
            content_segment_id=1,
            order=0,
        )
    except EpisodeSegmentError:
        pass
    else:
        raise AssertionError(
            "EpisodeSegmentError era esperado."
        )


def test_create_and_persist_episode_segment_can_be_listed_and_updated():
    initialize_schema()

    segment_id = _create_content_segment()

    episode = create_and_persist_episode(
        title="Episódio com segmentos",
    )

    first = create_and_persist_episode_segment(
        episode_id=episode["id"],
        content_segment_id=segment_id,
        order=0,
        role="intro",
    )

    second = create_and_persist_episode_segment(
        episode_id=episode["id"],
        content_segment_id=segment_id,
        order=1,
        role="content",
    )

    segments = list_episode_segments(
        episode["id"]
    )

    assert len(segments) == 2
    assert segments[0]["id"] == first["id"]
    assert segments[0]["segment_order"] == 0
    assert segments[1]["id"] == second["id"]
    assert segments[1]["segment_order"] == 1

    updated = update_episode_segment_status(
        first["id"],
        "completed",
    )

    assert updated is True

    persisted = get_episode_segment(first["id"])

    assert persisted is not None
    assert persisted["status"] == "completed"


def test_same_content_segment_can_be_reused_in_multiple_episodes():
    initialize_schema()

    content_segment_id = _create_content_segment()

    episode_a = create_and_persist_episode(
        title="Episódio A",
    )

    episode_b = create_and_persist_episode(
        title="Episódio B",
    )

    segment_a = create_and_persist_episode_segment(
        episode_id=episode_a["id"],
        content_segment_id=content_segment_id,
        order=0,
    )

    segment_b = create_and_persist_episode_segment(
        episode_id=episode_b["id"],
        content_segment_id=content_segment_id,
        order=3,
    )

    assert (
        segment_a["content_segment_id"]
        == content_segment_id
    )
    assert (
        segment_b["content_segment_id"]
        == content_segment_id
    )

    assert segment_a["episode_id"] != segment_b["episode_id"]
    assert segment_a["segment_order"] == 0
    assert segment_b["segment_order"] == 3


def test_episode_segment_requires_existing_foreign_keys():
    initialize_schema()

    try:
        create_and_persist_episode_segment(
            episode_id=999999,
            content_segment_id=999999,
            order=0,
        )
    except Exception:
        pass
    else:
        raise AssertionError(
            "A persistência deveria rejeitar FK inexistente."
        )


def test_episode_persistence_does_not_create_render_or_youtube_state():
    initialize_schema()

    episode = create_and_persist_episode(
        title="Episódio isolado",
    )

    assert "render_job_id" not in episode
    assert "video_id" not in episode
    assert "youtube_video_id" not in episode
    assert "youtube_publication_id" not in episode


def test_episode_segment_persistence_does_not_create_render_or_youtube_state():
    initialize_schema()

    segment_id = _create_content_segment()

    episode = create_and_persist_episode(
        title="Episódio isolado",
    )

    episode_segment = create_and_persist_episode_segment(
        episode_id=episode["id"],
        content_segment_id=segment_id,
        order=0,
    )

    assert "render_job_id" not in episode_segment
    assert "video_id" not in episode_segment
    assert "youtube_video_id" not in episode_segment
    assert "youtube_publication_id" not in episode_segment
