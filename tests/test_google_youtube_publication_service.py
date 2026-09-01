import app.services.google_youtube_publication_service as service


class FakePublisher:
    pass


def test_publish_youtube_publication_with_google_composes_and_delegates(
    monkeypatch,
):
    publication_id = 123
    token_file = "/tmp/youtube_token.json"

    publisher = FakePublisher()
    persisted_result = {
        "id": publication_id,
        "status": "published",
        "youtube_video_id": "youtube-123",
    }

    calls = []

    def fake_create_google_youtube_publisher(*, token_file):
        calls.append(("factory", token_file))
        return publisher

    def fake_publish_youtube_publication(
        received_publication_id,
        received_publisher,
    ):
        calls.append(
            (
                "orchestration",
                received_publication_id,
                received_publisher,
            )
        )
        return persisted_result

    monkeypatch.setattr(
        service,
        "create_google_youtube_publisher",
        fake_create_google_youtube_publisher,
    )
    monkeypatch.setattr(
        service,
        "publish_youtube_publication",
        fake_publish_youtube_publication,
    )

    result = service.publish_youtube_publication_with_google(
        publication_id=publication_id,
        token_file=token_file,
    )

    assert result is persisted_result

    assert calls == [
        ("factory", token_file),
        ("orchestration", publication_id, publisher),
    ]


def test_publish_youtube_publication_with_google_requires_token_file(
    monkeypatch,
):
    called = False

    def fake_create_google_youtube_publisher(*, token_file):
        nonlocal called
        called = True
        return FakePublisher()

    monkeypatch.setattr(
        service,
        "create_google_youtube_publisher",
        fake_create_google_youtube_publisher,
    )

    try:
        service.publish_youtube_publication_with_google(
            publication_id=123,
            token_file="",
        )
    except ValueError as exc:
        assert str(exc) == "token_file is required"
    else:
        raise AssertionError(
            "Expected ValueError when token_file is empty"
        )

    assert called is False


def test_publish_youtube_publication_with_google_requires_publication_id():
    try:
        service.publish_youtube_publication_with_google(
            publication_id=None,
            token_file="/tmp/youtube_token.json",
        )
    except ValueError as exc:
        assert str(exc) == "publication_id is required"
    else:
        raise AssertionError(
            "Expected ValueError when publication_id is missing"
        )
