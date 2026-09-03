import pytest

from app.database.content_segment_repository import (
    insert_content_segment,
)
from app.database.content_unit_repository import (
    insert_content_unit,
)
from app.database.episode_repository import (
    get_episode,
    insert_episode,
    list_episodes,
    update_episode_status,
)
from app.database.episode_segment_repository import (
    get_episode_segment,
    insert_episode_segment,
    list_episode_segments,
    update_episode_segment_status,
)
from app.database.ideas_repository import insert_idea
from app.database.schema import initialize_schema
from app.database.scripts_repository import insert_script


@pytest.fixture(autouse=True)
def setup_database():
    initialize_schema()


def create_dependencies():
    idea_id = insert_idea(
        title="GTA 6",
        description="Teste de dependências.",
    )

    script_id = insert_script(
        idea_id=idea_id,
        title="Script GTA 6",
        content="Conteúdo do script.",
    )

    content_item_id = insert_content_unit(
        content_item_id=1,
        title="Unidade GTA 6",
        unit_type="segment",
        duration_seconds=60,
        media_format="landscape_16_9",
        script_id=script_id,
        idea_id=idea_id,
        objective="Teste",
        hook="Hook",
        narration="Narração",
        visual_requirements=[],
    )

    return idea_id, script_id, content_item_id


def create_content_segment_for_test(
    *,
    content_unit_id: int,
    duration_seconds: float = 60,
):
    return insert_content_segment(
        content_unit_id=content_unit_id,
        segment_order=0,
        duration_seconds=duration_seconds,
        media_format="landscape_16_9",
        source_start_seconds=0,
        source_end_seconds=duration_seconds,
        role="content",
    )


def test_insert_and_get_episode():
    episode_id = insert_episode(
        title="GTA 6 — Episódio 001",
        target_duration_seconds=900,
        min_duration_seconds=840,
        max_duration_seconds=960,
    )

    episode = get_episode(episode_id)

    assert episode is not None
    assert episode["id"] == episode_id
    assert episode["title"] == "GTA 6 — Episódio 001"
    assert episode["target_duration_seconds"] == 900
    assert episode["min_duration_seconds"] == 840
    assert episode["max_duration_seconds"] == 960
    assert episode["status"] == "draft"
    assert episode["created_at"] is not None
    assert episode["updated_at"] is not None


def test_get_missing_episode_returns_none():
    assert get_episode(999999) is None


def test_list_episodes():
    first_id = insert_episode(
        title="Episode A",
        target_duration_seconds=900,
        min_duration_seconds=840,
        max_duration_seconds=960,
        status="draft",
    )

    second_id = insert_episode(
        title="Episode B",
        target_duration_seconds=900,
        min_duration_seconds=840,
        max_duration_seconds=960,
        status="ready",
    )

    episodes = list_episodes()

    ids = [episode["id"] for episode in episodes]

    assert first_id in ids
    assert second_id in ids


def test_list_episodes_can_filter_status():
    insert_episode(
        title="Draft Episode",
        target_duration_seconds=900,
        min_duration_seconds=840,
        max_duration_seconds=960,
        status="draft",
    )

    insert_episode(
        title="Ready Episode",
        target_duration_seconds=900,
        min_duration_seconds=840,
        max_duration_seconds=960,
        status="ready",
    )

    ready = list_episodes(status="ready")

    assert len(ready) == 1
    assert ready[0]["title"] == "Ready Episode"


def test_update_episode_status():
    episode_id = insert_episode(
        title="GTA 6",
        target_duration_seconds=900,
        min_duration_seconds=840,
        max_duration_seconds=960,
    )

    assert update_episode_status(
        episode_id,
        "ready",
    ) is True

    episode = get_episode(episode_id)

    assert episode is not None
    assert episode["status"] == "ready"


def test_update_missing_episode_returns_false():
    assert (
        update_episode_status(
            999999,
            "ready",
        )
        is False
    )


def test_insert_and_get_episode_segment():
    _, _, content_unit_id = create_dependencies()

    content_segment_id = create_content_segment_for_test(
        content_unit_id=content_unit_id,
    )

    episode_id = insert_episode(
        title="Episode 001",
        target_duration_seconds=900,
        min_duration_seconds=840,
        max_duration_seconds=960,
    )

    episode_segment_id = insert_episode_segment(
        episode_id=episode_id,
        content_segment_id=content_segment_id,
        episode_order=0,
        start_offset_seconds=0,
        role="content",
    )

    segment = get_episode_segment(
        episode_segment_id,
    )

    assert segment is not None
    assert segment["id"] == episode_segment_id
    assert segment["episode_id"] == episode_id
    assert segment["content_segment_id"] == content_segment_id
    assert segment["segment_order"] == 0
    assert segment["start_offset_seconds"] == 0
    assert segment["role"] == "content"
    assert segment["status"] == "ready"


def test_episode_segments_are_returned_in_episode_order():
    _, _, content_unit_id = create_dependencies()

    segment_a = create_content_segment_for_test(
        content_unit_id=content_unit_id,
    )

    segment_b = insert_content_segment(
        content_unit_id=content_unit_id,
        segment_order=1,
        duration_seconds=30,
        media_format="landscape_16_9",
        source_start_seconds=0,
        source_end_seconds=30,
        role="content",
    )

    segment_c = insert_content_segment(
        content_unit_id=content_unit_id,
        segment_order=2,
        duration_seconds=45,
        media_format="portrait_9_16",
        source_start_seconds=0,
        source_end_seconds=45,
        role="content",
    )

    episode_id = insert_episode(
        title="Episode 001",
        target_duration_seconds=900,
        min_duration_seconds=840,
        max_duration_seconds=960,
    )

    insert_episode_segment(
        episode_id=episode_id,
        content_segment_id=segment_c,
        episode_order=2,
    )

    insert_episode_segment(
        episode_id=episode_id,
        content_segment_id=segment_a,
        episode_order=0,
    )

    insert_episode_segment(
        episode_id=episode_id,
        content_segment_id=segment_b,
        episode_order=1,
    )

    segments = list_episode_segments(episode_id)

    assert [item["segment_order"] for item in segments] == [
        0,
        1,
        2,
    ]

    assert [
        item["content_segment_id"]
        for item in segments
    ] == [
        segment_a,
        segment_b,
        segment_c,
    ]


def test_same_content_segment_can_be_reused_in_different_episodes():
    _, _, content_unit_id = create_dependencies()

    content_segment_id = create_content_segment_for_test(
        content_unit_id=content_unit_id,
    )

    episode_a = insert_episode(
        title="Episode A",
        target_duration_seconds=900,
        min_duration_seconds=840,
        max_duration_seconds=960,
    )

    episode_b = insert_episode(
        title="Episode B",
        target_duration_seconds=900,
        min_duration_seconds=840,
        max_duration_seconds=960,
    )

    first = insert_episode_segment(
        episode_id=episode_a,
        content_segment_id=content_segment_id,
        episode_order=0,
    )

    second = insert_episode_segment(
        episode_id=episode_b,
        content_segment_id=content_segment_id,
        episode_order=5,
    )

    assert first != second

    first_row = get_episode_segment(first)
    second_row = get_episode_segment(second)

    assert first_row["content_segment_id"] == content_segment_id
    assert second_row["content_segment_id"] == content_segment_id
    assert first_row["episode_id"] == episode_a
    assert second_row["episode_id"] == episode_b


def test_same_episode_cannot_have_duplicate_segment_order():
    _, _, content_unit_id = create_dependencies()

    segment_a = create_content_segment_for_test(
        content_unit_id=content_unit_id,
    )

    segment_b = insert_content_segment(
        content_unit_id=content_unit_id,
        segment_order=1,
        duration_seconds=30,
        media_format="landscape_16_9",
        source_start_seconds=0,
        source_end_seconds=30,
        role="content",
    )

    episode_id = insert_episode(
        title="Episode 001",
        target_duration_seconds=900,
        min_duration_seconds=840,
        max_duration_seconds=960,
    )

    insert_episode_segment(
        episode_id=episode_id,
        content_segment_id=segment_a,
        episode_order=0,
    )

    with pytest.raises(Exception):
        insert_episode_segment(
            episode_id=episode_id,
            content_segment_id=segment_b,
            episode_order=0,
        )


def test_update_episode_segment_status():
    _, _, content_unit_id = create_dependencies()

    content_segment_id = create_content_segment_for_test(
        content_unit_id=content_unit_id,
    )

    episode_id = insert_episode(
        title="Episode 001",
        target_duration_seconds=900,
        min_duration_seconds=840,
        max_duration_seconds=960,
    )

    episode_segment_id = insert_episode_segment(
        episode_id=episode_id,
        content_segment_id=content_segment_id,
        episode_order=0,
    )

    assert update_episode_segment_status(
        episode_segment_id,
        "processing",
    ) is True

    segment = get_episode_segment(
        episode_segment_id,
    )

    assert segment is not None
    assert segment["status"] == "processing"


def test_update_missing_episode_segment_returns_false():
    assert (
        update_episode_segment_status(
            999999,
            "processing",
        )
        is False
    )
