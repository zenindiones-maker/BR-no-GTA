import app.services.google_youtube_publisher_factory as factory
from app.services.google_youtube_publisher import (
    GoogleYouTubePublisher,
)


class FakeCredentials:
    pass


class FakeYouTubeService:
    def __init__(self):
        self.videos_calls = 0

    def videos(self):
        self.videos_calls += 1
        raise AssertionError(
            "YouTube API must not be called during publisher composition"
        )


def test_create_google_youtube_publisher_composes_real_dependencies(
    monkeypatch,
    tmp_path,
):
    token_file = tmp_path / "youtube_token.json"
    client_secrets_file = tmp_path / "client_secret.json"

    credentials = FakeCredentials()
    youtube_service = FakeYouTubeService()

    authorization_runner = object()
    request = object()

    calls = []

    def fake_get_youtube_credentials(
        *,
        token_file,
        client_secrets_file,
        authorization_runner,
        request,
    ):
        calls.append(
            (
                "credentials",
                token_file,
                client_secrets_file,
                authorization_runner,
                request,
            )
        )
        return credentials

    def fake_create_youtube_service(received_credentials):
        calls.append(
            (
                "service",
                received_credentials,
            )
        )
        return youtube_service

    monkeypatch.setattr(
        factory,
        "get_youtube_credentials",
        fake_get_youtube_credentials,
    )

    monkeypatch.setattr(
        factory,
        "create_youtube_service",
        fake_create_youtube_service,
    )

    result = factory.create_google_youtube_publisher(
        token_file=str(token_file),
        client_secrets_file=str(client_secrets_file),
        authorization_runner=authorization_runner,
        request=request,
    )

    assert isinstance(
        result,
        GoogleYouTubePublisher,
    )

    assert result.youtube_service is youtube_service

    assert calls == [
        (
            "credentials",
            str(token_file),
            str(client_secrets_file),
            authorization_runner,
            request,
        ),
        (
            "service",
            credentials,
        ),
    ]

    assert youtube_service.videos_calls == 0


def test_create_google_youtube_publisher_requires_token_file():
    try:
        factory.create_google_youtube_publisher(
            token_file="",
            client_secrets_file="client_secret.json",
        )
    except ValueError as exc:
        assert str(exc) == "token_file is required"
    else:
        raise AssertionError(
            "Expected ValueError when token_file is empty"
        )


def test_create_google_youtube_publisher_requires_client_secrets_file(
    tmp_path,
):
    token_file = tmp_path / "youtube_token.json"

    try:
        factory.create_google_youtube_publisher(
            token_file=str(token_file),
            client_secrets_file="",
        )
    except ValueError as exc:
        assert str(exc) == "client_secrets_file is required"
    else:
        raise AssertionError(
            "Expected ValueError when client_secrets_file is missing"
        )
