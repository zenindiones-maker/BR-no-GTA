from unittest.mock import Mock

import app.services.google_youtube_client as google_youtube_client


class FakeCredentials:
    pass


def test_create_youtube_service_requires_credentials():
    try:
        google_youtube_client.create_youtube_service(None)
    except ValueError as exc:
        assert str(exc) == "credentials are required"
    else:
        raise AssertionError(
            "Expected ValueError when credentials are missing"
        )


def test_create_youtube_service_builds_youtube_v3_client(
    monkeypatch,
):
    credentials = FakeCredentials()
    captured = {}

    def fake_build(
        service_name,
        version,
        *,
        credentials,
    ):
        captured["service_name"] = service_name
        captured["version"] = version
        captured["credentials"] = credentials
        return "fake-youtube-service"

    monkeypatch.setattr(
        google_youtube_client,
        "build",
        fake_build,
    )

    result = google_youtube_client.create_youtube_service(
        credentials,
    )

    assert result == "fake-youtube-service"
    assert captured["service_name"] == "youtube"
    assert captured["version"] == "v3"
    assert captured["credentials"] is credentials


def test_create_youtube_service_does_not_execute_oauth(
    monkeypatch,
):
    credentials = Mock()

    monkeypatch.setattr(
        google_youtube_client,
        "build",
        lambda service_name, version, *, credentials: (
            "fake-youtube-service"
        ),
    )

    result = google_youtube_client.create_youtube_service(
        credentials,
    )

    assert result == "fake-youtube-service"
    credentials.refresh.assert_not_called()
    credentials.authorize.assert_not_called()
