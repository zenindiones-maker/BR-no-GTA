import pytest

import app.services.google_youtube_publication_service as service


class FakePublisher:
    def __init__(self):
        self.publish_calls = 0

    def publish(self, publication):
        self.publish_calls += 1
        raise AssertionError(
            "Google publication service must not call publisher.publish() directly"
        )


def test_publish_youtube_publication_with_google_composes_and_delegates(
    monkeypatch,
):
    publication_id = 123
    token_file = "/tmp/youtube_token.json"
    client_secrets_file = "/tmp/client_secret.json"
    authorization_runner = object()
    request = object()

    publisher = FakePublisher()

    persisted_result = {
        "id": publication_id,
        "status": "published",
        "youtube_video_id": "youtube-123",
        "youtube_url": "https://www.youtube.com/watch?v=youtube-123",
    }

    calls = []

    def fake_create_google_youtube_publisher(
        *,
        token_file,
        client_secrets_file,
        authorization_runner,
        request,
    ):
        calls.append(
            (
                "factory",
                token_file,
                client_secrets_file,
                authorization_runner,
                request,
            )
        )
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
        client_secrets_file=client_secrets_file,
        authorization_runner=authorization_runner,
        request=request,
    )

    assert result is persisted_result

    assert calls == [
        (
            "factory",
            token_file,
            client_secrets_file,
            authorization_runner,
            request,
        ),
        (
            "orchestration",
            publication_id,
            publisher,
        ),
    ]

    assert publisher.publish_calls == 0


def test_publish_youtube_publication_with_google_rejects_none_publication_id():
    with pytest.raises(
        ValueError,
        match=r"^publication_id is required$",
    ):
        service.publish_youtube_publication_with_google(
            publication_id=None,
            token_file="/tmp/youtube_token.json",
            client_secrets_file="/tmp/client_secret.json",
        )


def test_publish_youtube_publication_with_google_rejects_empty_token_file():
    with pytest.raises(
        ValueError,
        match=r"^token_file is required$",
    ):
        service.publish_youtube_publication_with_google(
            publication_id=123,
            token_file="",
            client_secrets_file="/tmp/client_secret.json",
        )


def test_publish_youtube_publication_with_google_rejects_whitespace_token_file():
    with pytest.raises(
        ValueError,
        match=r"^token_file is required$",
    ):
        service.publish_youtube_publication_with_google(
            publication_id=123,
            token_file="   ",
            client_secrets_file="/tmp/client_secret.json",
        )


def test_publish_youtube_publication_with_google_rejects_empty_client_secrets_file():
    with pytest.raises(
        ValueError,
        match=r"^client_secrets_file is required$",
    ):
        service.publish_youtube_publication_with_google(
            publication_id=123,
            token_file="/tmp/youtube_token.json",
            client_secrets_file="",
        )


def test_publish_youtube_publication_with_google_rejects_whitespace_client_secrets_file():
    with pytest.raises(
        ValueError,
        match=r"^client_secrets_file is required$",
    ):
        service.publish_youtube_publication_with_google(
            publication_id=123,
            token_file="/tmp/youtube_token.json",
            client_secrets_file="   ",
        )


def test_publish_youtube_publication_with_google_does_not_call_factory_on_invalid_input(
    monkeypatch,
):
    calls = []

    def fake_create_google_youtube_publisher(
        *,
        token_file,
        client_secrets_file,
        authorization_runner,
        request,
    ):
        calls.append(
            (
                token_file,
                client_secrets_file,
                authorization_runner,
                request,
            )
        )
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
            client_secrets_file="/tmp/client_secret.json",
        )

    with pytest.raises(
        ValueError,
        match=r"^token_file is required$",
    ):
        service.publish_youtube_publication_with_google(
            publication_id=123,
            token_file="",
            client_secrets_file="/tmp/client_secret.json",
        )

    with pytest.raises(
        ValueError,
        match=r"^client_secrets_file is required$",
    ):
        service.publish_youtube_publication_with_google(
            publication_id=123,
            token_file="/tmp/youtube_token.json",
            client_secrets_file="",
        )

    assert calls == []


def test_publish_youtube_publication_with_google_propagates_factory_error(
    monkeypatch,
):
    def fake_create_google_youtube_publisher(
        *,
        token_file,
        client_secrets_file,
        authorization_runner,
        request,
    ):
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
            client_secrets_file="/tmp/client_secret.json",
        )


def test_publish_youtube_publication_with_google_propagates_orchestration_error(
    monkeypatch,
):
    publisher = FakePublisher()

    def fake_create_google_youtube_publisher(
        *,
        token_file,
        client_secrets_file,
        authorization_runner,
        request,
    ):
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
            client_secrets_file="/tmp/client_secret.json",
        )


def test_publish_youtube_publication_with_google_uses_factory_output_directly(
    monkeypatch,
):
    factory_publisher = object()
    received = []

    def fake_create_google_youtube_publisher(
        *,
        token_file,
        client_secrets_file,
        authorization_runner,
        request,
    ):
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
        client_secrets_file="/tmp/client_secret.json",
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


def test_publish_google_uses_canonical_configuration_when_paths_are_omitted(
    monkeypatch,
):
    import app.services.google_youtube_publication_service as service

    calls = {}

    class FakePublisher:
        pass

    fake_publisher = FakePublisher()

    def fake_get_youtube_token_file():
        calls["token_file"] = True
        return "/canonical/token.json"

    def fake_get_youtube_client_secrets_file():
        calls["client_secrets_file"] = True
        return "/canonical/client_secret.json"

    def fake_create_google_youtube_publisher(**kwargs):
        calls["factory"] = kwargs
        return fake_publisher

    def fake_publish_youtube_publication(
        publication_id,
        publisher,
    ):
        calls["orchestration"] = (
            publication_id,
            publisher,
        )
        return {"id": publication_id}

    monkeypatch.setattr(
        service,
        "get_youtube_token_file",
        fake_get_youtube_token_file,
    )
    monkeypatch.setattr(
        service,
        "get_youtube_client_secrets_file",
        fake_get_youtube_client_secrets_file,
    )
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
        publication_id=42,
    )

    assert calls["token_file"] is True
    assert calls["client_secrets_file"] is True

    assert calls["factory"] == {
        "token_file": "/canonical/token.json",
        "client_secrets_file": "/canonical/client_secret.json",
        "authorization_runner": None,
        "request": None,
    }

    assert calls["orchestration"] == (
        42,
        fake_publisher,
    )

    assert result == {"id": 42}


def test_publish_google_preserves_explicit_oauth_paths(
    monkeypatch,
):
    import app.services.google_youtube_publication_service as service

    calls = {}

    def fail_canonical_configuration():
        raise AssertionError(
            "canonical configuration should not be used"
        )

    def fake_create_google_youtube_publisher(**kwargs):
        calls["factory"] = kwargs
        return object()

    def fake_publish_youtube_publication(
        publication_id,
        publisher,
    ):
        return {"id": publication_id}

    monkeypatch.setattr(
        service,
        "get_youtube_token_file",
        fail_canonical_configuration,
    )
    monkeypatch.setattr(
        service,
        "get_youtube_client_secrets_file",
        fail_canonical_configuration,
    )
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
        publication_id=42,
        token_file="/explicit/token.json",
        client_secrets_file="/explicit/client_secret.json",
    )

    assert calls["factory"] == {
        "token_file": "/explicit/token.json",
        "client_secrets_file": "/explicit/client_secret.json",
        "authorization_runner": None,
        "request": None,
    }

    assert result == {"id": 42}
