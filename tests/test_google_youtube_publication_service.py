import pytest

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
        "youtube_url": "https://www.youtube.com/watch?v=youtube-123",
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


def test_publish_youtube_publication_with_google_rejects_none_publication_id():
    with pytest.raises(
        ValueError,
        match=r"^publication_id is required$",
    ):
        service.publish_youtube_publication_with_google(
            publication_id=None,
            token_file="/tmp/youtube_token.json",
        )


def test_publish_youtube_publication_with_google_rejects_empty_token_file():
    with pytest.raises(
        ValueError,
        match=r"^token_file is required$",
    ):
        service.publish_youtube_publication_with_google(
            publication_id=123,
            token_file="",
        )


def test_publish_youtube_publication_with_google_rejects_whitespace_token_file():
    with pytest.raises(
        ValueError,
        match=r"^token_file is required$",
    ):
        service.publish_youtube_publication_with_google(
            publication_id=123,
            token_file="   ",
        )


def test_publish_youtube_publication_with_google_does_not_call_factory_on_invalid_input(
    monkeypatch,
):
    calls = []

    def fake_create_google_youtube_publisher(*, token_file):
        calls.append(token_file)
        return FakePublisher()

    monkeypatch.setattr(
        service,
        "create_google_youtube_publisher",
        fake_create_google_youtube_publisher,
    )

    with pytest.raises(
        ValueError,
        match=r"^publication_id is required$",
    ):
        service.publish_youtube_publication_with_google(
            publication_id=None,
            token_file="/tmp/youtube_token.json",
        )

    with pytest.raises(
        ValueError,
        match=r"^token_file is required$",
    ):
        service.publish_youtube_publication_with_google(
            publication_id=123,
            token_file="",
        )

    assert calls == []


def test_publish_youtube_publication_with_google_propagates_factory_error(
    monkeypatch,
):
    def fake_create_google_youtube_publisher(*, token_file):
        raise RuntimeError("credential loading failed")

    monkeypatch.setattr(
        service,
        "create_google_youtube_publisher",
        fake_create_google_youtube_publisher,
    )

    with pytest.raises(
        RuntimeError,
        match=r"^credential loading failed$",
    ):
        service.publish_youtube_publication_with_google(
            publication_id=123,
            token_file="/tmp/youtube_token.json",
        )


def test_publish_youtube_publication_with_google_propagates_orchestration_error(
    monkeypatch,
):
    publisher = FakePublisher()

    def fake_create_google_youtube_publisher(*, token_file):
        return publisher

    def fake_publish_youtube_publication(
        publication_id,
        received_publisher,
    ):
        assert publication_id == 123
        assert received_publisher is publisher
        raise RuntimeError("publication orchestration failed")

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

    with pytest.raises(
        RuntimeError,
        match=r"^publication orchestration failed$",
    ):
        service.publish_youtube_publication_with_google(
            publication_id=123,
            token_file="/tmp/youtube_token.json",
        )


def test_publish_youtube_publication_with_google_uses_factory_output_directly(
    monkeypatch,
):
    factory_publisher = object()
    received = []

    def fake_create_google_youtube_publisher(*, token_file):
        return factory_publisher

    def fake_publish_youtube_publication(
        publication_id,
        publisher,
    ):
        received.append(
            (
                publication_id,
                publisher,
            )
        )
        return {
            "id": publication_id,
            "status": "published",
        }

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
        publication_id=456,
        token_file="/tmp/youtube_token.json",
    )

    assert result == {
        "id": 456,
        "status": "published",
    }

    assert received == [
        (
            456,
            factory_publisher,
        )
    ]
