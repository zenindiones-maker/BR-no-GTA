import pytest

from app.services.episode_service import (
    EpisodeError,
    create_episode,
    is_episode_duration_valid,
    validate_episode,
)


def test_create_episode_defaults_to_15_minutes():
    episode = create_episode(
        title="GTA 6 — Notícias da Semana",
    )

    assert episode["title"] == "GTA 6 — Notícias da Semana"
    assert episode["target_duration_seconds"] == 900.0
    assert episode["min_duration_seconds"] == 840.0
    assert episode["max_duration_seconds"] == 960.0
    assert episode["status"] == "draft"


def test_create_episode_normalizes_title_and_status():
    episode = create_episode(
        title="  GTA 6  ",
        status="  ready  ",
    )

    assert episode["title"] == "GTA 6"
    assert episode["status"] == "ready"


@pytest.mark.parametrize(
    "duration",
    [0, -1, -10],
)
def test_invalid_target_duration_is_rejected(duration):
    with pytest.raises(EpisodeError):
        create_episode(
            title="GTA 6",
            target_duration_seconds=duration,
        )


def test_minimum_duration_cannot_exceed_target():
    with pytest.raises(EpisodeError):
        create_episode(
            title="GTA 6",
            target_duration_seconds=900,
            min_duration_seconds=901,
        )


def test_target_duration_cannot_exceed_maximum():
    with pytest.raises(EpisodeError):
        create_episode(
            title="GTA 6",
            target_duration_seconds=961,
            max_duration_seconds=960,
        )


def test_empty_title_is_rejected():
    with pytest.raises(EpisodeError):
        create_episode(title="   ")


def test_validate_episode_accepts_valid_episode():
    episode = create_episode(
        title="GTA 6",
    )

    validated = validate_episode(episode)

    assert validated == episode


def test_validate_episode_rejects_missing_field():
    with pytest.raises(EpisodeError):
        validate_episode(
            {
                "title": "GTA 6",
                "target_duration_seconds": 900,
            }
        )


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (840, True),
        (900, True),
        (960, True),
        (839.99, False),
        (960.01, False),
    ],
)
def test_episode_duration_window(
    duration,
    expected,
):
    episode = create_episode(
        title="GTA 6",
    )

    assert (
        is_episode_duration_valid(
            episode,
            duration,
        )
        is expected
    )


def test_episode_has_no_render_or_publication_responsibility():
    episode = create_episode(
        title="GTA 6",
    )

    assert "file_path" not in episode
    assert "render_job_id" not in episode
    assert "youtube_video_id" not in episode
