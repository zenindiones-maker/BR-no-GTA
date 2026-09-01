import app.services.google_youtube_publisher_factory as factory


class FakeCredentials:
    pass


class FakeYouTubeService:
    pass


class FakePublisher:
    def __init__(self, *, youtube_service):
        self.youtube_service = youtube_service


def test_create_google_youtube_publisher_composes_real_dependencies(
    monkeypatch,
    tmp_path,
):
    token_file = tmp_path / "youtube_token.json"

    credentials = FakeCredentials()
    youtube_service = FakeYouTubeService()

    calls = []

    def fake_load_youtube_credentials(*, token_file):
        calls.append(("load", token_file))
        return credentials

    def fake_create_youtube_service(received_credentials):
        calls.append(("service", received_credentials))
        return youtube_service

    def fake_publisher(*, youtube_service):
        calls.append(("publisher", youtube_service))
        return FakePublisher(youtube_service=youtube_service)

    monkeypatch.setattr(
        factory,
        "load_youtube_credentials",
        fake_load_youtube_credentials,
    )
    monkeypatch.setattr(
        factory,
        "create_youtube_service",
        fake_create_youtube_service,
    )
    monkeypatch.setattr(
        factory,
        "GoogleYouTubePublisher",
        fake_publisher,
    )

    result = factory.create_google_youtube_publisher(
        token_file=str(token_file),
    )

    assert isinstance(result, FakePublisher)
    assert result.youtube_service is youtube_service

    assert calls == [
        ("load", str(token_file)),
        ("service", credentials),
        ("publisher", youtube_service),
    ]


def test_create_google_youtube_publisher_requires_token_file():
    try:
        factory.create_google_youtube_publisher(
            token_file="",
        )
    except ValueError as exc:
        assert str(exc) == "token_file is required"
    else:
        raise AssertionError(
            "Expected ValueError when token_file is empty"
        )
