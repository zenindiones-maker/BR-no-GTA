import pytest

from app.database.content_segment_repository import (
    insert_content_segment,
)
from app.database.content_unit_repository import (
    insert_content_unit,
)
from app.database.episode_repository import (
    list_episodes,
)
from app.database.episode_segment_repository import (
    list_episode_segments,
)
from app.database.ideas_repository import insert_idea
from app.database.schema import initialize_schema
from app.database.scripts_repository import insert_script
from app.services.content_item_service import create_content_item
from app.services.episode_composition_service import (
    EpisodeCompositionError,
    calculate_composition_duration,
    compose_episode,
    validate_episode_composition,
)


@pytest.fixture(autouse=True)
def setup_database():
    initialize_schema()


def create_content_segment_for_test(
    *,
    duration_seconds: float,
    segment_order: int,
) -> int:
    idea_id = insert_idea(
        title="GTA 6",
        description="Teste de composição.",
    )

    script_id = insert_script(
        idea_id=idea_id,
        title="Script GTA 6",
        content="Conteúdo do script.",
    )

    content_item = create_content_item(
        {
            "script_id": script_id,
            "idea_id": idea_id,
            "objective": "Teste de composição.",
            "audience": "Público GTA 6.",
            "estimated_duration_seconds": duration_seconds,
            "format": "segment",
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

    content_unit_id = insert_content_unit(
        content_item_id=content_item["id"],
        title="Unidade GTA 6",
        unit_type="segment",
        duration_seconds=duration_seconds,
        media_format="landscape_16_9",
        script_id=script_id,
        idea_id=idea_id,
        objective="Teste",
        hook="Hook",
        narration="Narração",
        visual_requirements=[],
    )

    return insert_content_segment(
        content_unit_id=content_unit_id,
        segment_order=segment_order,
        duration_seconds=duration_seconds,
        media_format="landscape_16_9",
        source_start_seconds=0,
        source_end_seconds=duration_seconds,
        role="content",
    )


def test_calculate_composition_duration():
    segments = [
        {"duration_seconds": 100},
        {"duration_seconds": 200},
        {"duration_seconds": 300},
    ]

    assert calculate_composition_duration(segments) == 600.0


def test_calculate_composition_duration_rejects_invalid_duration():
    with pytest.raises(EpisodeCompositionError):
        calculate_composition_duration(
            [{"duration_seconds": 0}]
        )


def test_validate_episode_composition_accepts_15_minute_window():
    segments = [
        {"duration_seconds": 420},
        {"duration_seconds": 480},
    ]

    duration = validate_episode_composition(
        target_duration_seconds=900,
        min_duration_seconds=840,
        max_duration_seconds=960,
        segments=segments,
    )

    assert duration == 900.0


def test_validate_episode_composition_rejects_short_episode():
    segments = [
        {"duration_seconds": 300},
        {"duration_seconds": 300},
    ]

    with pytest.raises(EpisodeCompositionError):
        validate_episode_composition(
            target_duration_seconds=900,
            min_duration_seconds=840,
            max_duration_seconds=960,
            segments=segments,
        )


def test_validate_episode_composition_rejects_long_episode():
    segments = [
        {"duration_seconds": 500},
        {"duration_seconds": 500},
    ]

    with pytest.raises(EpisodeCompositionError):
        validate_episode_composition(
            target_duration_seconds=900,
            min_duration_seconds=840,
            max_duration_seconds=960,
            segments=segments,
        )


def test_compose_episode_persists_episode_and_segments():
    segment_a = create_content_segment_for_test(
        duration_seconds=420,
        segment_order=0,
    )

    segment_b = create_content_segment_for_test(
        duration_seconds=480,
        segment_order=0,
    )

    result = compose_episode(
        title="GTA 6 — Episódio de teste",
        content_segment_ids=[
            segment_a,
            segment_b,
        ],
    )

    assert result["status"] == "composed"
    assert result["segment_count"] == 2
    assert result["duration_seconds"] == 900.0
    assert result["duration_valid"] is True

    episodes = list_episodes()

    assert len(episodes) == 1
    assert episodes[0]["title"] == "GTA 6 — Episódio de teste"

    episode_segments = list_episode_segments(
        episodes[0]["id"]
    )

    assert len(episode_segments) == 2

    assert episode_segments[0]["content_segment_id"] == segment_a
    assert episode_segments[0]["segment_order"] == 0
    assert episode_segments[0]["start_offset_seconds"] == 0.0

    assert episode_segments[1]["content_segment_id"] == segment_b
    assert episode_segments[1]["segment_order"] == 1
    assert episode_segments[1]["start_offset_seconds"] == 420.0


def test_compose_episode_preserves_requested_order():
    segment_a = create_content_segment_for_test(
        duration_seconds=300,
        segment_order=0,
    )

    segment_b = create_content_segment_for_test(
        duration_seconds=540,
        segment_order=0,
    )

    result = compose_episode(
        title="GTA 6 — Ordem de montagem",
        content_segment_ids=[
            segment_b,
            segment_a,
        ],
    )

    assert result["duration_seconds"] == 840.0

    episode = result["episode"]
    episode_segments = result["episode_segments"]

    assert episode_segments[0]["content_segment_id"] == segment_b
    assert episode_segments[1]["content_segment_id"] == segment_a

    assert episode_segments[0]["start_offset_seconds"] == 0.0
    assert episode_segments[1]["start_offset_seconds"] == 540.0

    assert episode["target_duration_seconds"] == 900.0


def test_compose_episode_rejects_empty_selection():
    with pytest.raises(EpisodeCompositionError):
        compose_episode(
            title="Episode inválido",
            content_segment_ids=[],
        )


def test_compose_episode_rejects_missing_segment():
    with pytest.raises(EpisodeCompositionError):
        compose_episode(
            title="Episode inválido",
            content_segment_ids=[999999],
        )


def test_compose_episode_rejects_invalid_segment_id():
    with pytest.raises(EpisodeCompositionError):
        compose_episode(
            title="Episode inválido",
            content_segment_ids=[0],
        )
