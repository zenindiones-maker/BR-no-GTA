from app.services.publication_split_service import (
    PRODUCTION_DURATION_SECONDS,
    PUBLICATION_DURATION_SECONDS,
    build_publication_split,
)


def test_build_publication_split_creates_two_25_minute_publications():
    result = build_publication_split(
        video={
            "id": 123,
            "estimated_duration_seconds": PRODUCTION_DURATION_SECONDS,
        }
    )

    assert result["production_duration_seconds"] == 50 * 60
    assert result["publication_duration_seconds"] == 25 * 60
    assert result["publication_count"] == 2

    publications = result["publications"]

    assert len(publications) == 2

    assert publications[0] == {
        "video_id": 123,
        "sequence": 1,
        "start_seconds": 0,
        "end_seconds": 25 * 60,
        "duration_seconds": 25 * 60,
        "status": "ready",
    }

    assert publications[1] == {
        "video_id": 123,
        "sequence": 2,
        "start_seconds": 25 * 60,
        "end_seconds": 50 * 60,
        "duration_seconds": 25 * 60,
        "status": "ready",
    }


def test_build_publication_split_rejects_non_50_minute_video():
    try:
        build_publication_split(
            video={
                "id": 123,
                "estimated_duration_seconds": 25 * 60,
            }
        )
    except ValueError as exc:
        assert "50 minutos" in str(exc)
    else:
        raise AssertionError(
            "Uma produção diferente de 50 minutos deveria falhar."
        )
