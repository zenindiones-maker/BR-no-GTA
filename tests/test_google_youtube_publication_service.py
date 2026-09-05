from unittest.mock import Mock

import pytest

from app.database.youtube_repository import (
    get_youtube_publication,
    insert_youtube_publication,
)
from app.services.google_youtube_publication_service import (
    make_youtube_publication_public_with_google,
    process_next_youtube_publication,
    upload_youtube_publication_with_google,
)
from app.services.youtube_publisher import (
    YouTubeUploadResult,
    YouTubeVisibilityResult,
)
from tests.test_youtube_repository import _create_video


def _create_publication() -> int:
    content_item_id, video_id = _create_video()

    return insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="Teste Google Service",
        description="Descrição",
        tags=["gta6"],
        category_id="20",
        file_path="/tmp/video.mp4",
        privacy_status="private",
        publish_at=None,
    )


def test_upload_with_google_composes_factory_and_delegates(
    monkeypatch,
):
    publication_id = _create_publication()

    publisher = Mock()
    publisher.upload.return_value = YouTubeUploadResult(
        success=True,
        youtube_video_id="youtube123",
        youtube_url="https://www.youtube.com/watch?v=youtube123",
    )

    factory_calls = {}

    def fake_factory(**kwargs):
        factory_calls.update(kwargs)
        return publisher

    monkeypatch.setattr(
        "app.services.google_youtube_publication_service."
        "create_google_youtube_publisher",
        fake_factory,
    )

    result = upload_youtube_publication_with_google(
        publication_id=publication_id,
        token_file="/tmp/token.json",
        client_secrets_file="/tmp/client.json",
    )

    assert result["status"] == "uploaded"
    assert result["youtube_video_id"] == "youtube123"
    assert publisher.upload.call_count == 1

    assert factory_calls["token_file"] == "/tmp/token.json"
    assert factory_calls["client_secrets_file"] == "/tmp/client.json"


def test_upload_with_google_resolves_default_configuration(
    monkeypatch,
):
    publication_id = _create_publication()

    publisher = Mock()
    publisher.upload.return_value = YouTubeUploadResult(
        success=True,
        youtube_video_id="youtube123",
        youtube_url="https://www.youtube.com/watch?v=youtube123",
    )

    monkeypatch.setattr(
        "app.services.google_youtube_publication_service."
        "get_youtube_token_file",
        lambda: "/default/token.json",
    )
    monkeypatch.setattr(
        "app.services.google_youtube_publication_service."
        "get_youtube_client_secrets_file",
        lambda: "/default/client.json",
    )

    factory_calls = {}

    def fake_factory(**kwargs):
        factory_calls.update(kwargs)
        return publisher

    monkeypatch.setattr(
        "app.services.google_youtube_publication_service."
        "create_google_youtube_publisher",
        fake_factory,
    )

    result = upload_youtube_publication_with_google(
        publication_id=publication_id,
    )

    assert result["status"] == "uploaded"
    assert factory_calls["token_file"] == "/default/token.json"
    assert factory_calls["client_secrets_file"] == "/default/client.json"


def test_upload_with_google_rejects_invalid_publication_id(
    monkeypatch,
):
    factory = Mock()

    monkeypatch.setattr(
        "app.services.google_youtube_publication_service."
        "create_google_youtube_publisher",
        factory,
    )

    with pytest.raises(
        ValueError,
        match="publication_id must be a positive integer",
    ):
        upload_youtube_publication_with_google(
            publication_id=0,
            token_file="/tmp/token.json",
            client_secrets_file="/tmp/client.json",
        )

    factory.assert_not_called()


def test_upload_with_google_requires_token_file(monkeypatch):
    publication_id = _create_publication()

    monkeypatch.setattr(
        "app.services.google_youtube_publication_service."
        "get_youtube_token_file",
        lambda: "",
    )

    with pytest.raises(
        ValueError,
        match="token_file is required",
    ):
        upload_youtube_publication_with_google(
            publication_id=publication_id,
            client_secrets_file="/tmp/client.json",
        )


def test_upload_with_google_requires_client_secrets_file(
    monkeypatch,
):
    publication_id = _create_publication()

    monkeypatch.setattr(
        "app.services.google_youtube_publication_service."
        "get_youtube_client_secrets_file",
        lambda: "",
    )

    with pytest.raises(
        ValueError,
        match="client_secrets_file is required",
    ):
        upload_youtube_publication_with_google(
            publication_id=publication_id,
            token_file="/tmp/token.json",
        )


def test_make_public_with_google_delegates_to_visibility_orchestration(
    monkeypatch,
):
    publication_id = _create_publication()

    publisher = Mock()
    publisher.upload.return_value = YouTubeUploadResult(
        success=True,
        youtube_video_id="youtube123",
        youtube_url="https://www.youtube.com/watch?v=youtube123",
    )

    monkeypatch.setattr(
        "app.services.google_youtube_publication_service."
        "get_youtube_token_file",
        lambda: "/tmp/token.json",
    )
    monkeypatch.setattr(
        "app.services.google_youtube_publication_service."
        "get_youtube_client_secrets_file",
        lambda: "/tmp/client.json",
    )
    monkeypatch.setattr(
        "app.services.google_youtube_publication_service."
        "create_google_youtube_publisher",
        lambda **kwargs: publisher,
    )

    upload_youtube_publication_with_google(
        publication_id=publication_id,
        token_file="/tmp/token.json",
        client_secrets_file="/tmp/client.json",
    )

    publisher.make_public.return_value = YouTubeVisibilityResult(
        success=True,
    )

    result = make_youtube_publication_public_with_google(
        publication_id=publication_id,
        token_file="/tmp/token.json",
        client_secrets_file="/tmp/client.json",
    )

    assert result["status"] == "published"
    publisher.make_public.assert_called_once_with("youtube123")


def test_make_public_with_google_keeps_uploaded_on_failure(
    monkeypatch,
):
    publication_id = _create_publication()

    publisher = Mock()
    publisher.upload.return_value = YouTubeUploadResult(
        success=True,
        youtube_video_id="youtube123",
        youtube_url="https://www.youtube.com/watch?v=youtube123",
    )
    publisher.make_public.return_value = YouTubeVisibilityResult(
        success=False,
        error="Falha de visibilidade",
    )

    monkeypatch.setattr(
        "app.services.google_youtube_publication_service."
        "create_google_youtube_publisher",
        lambda **kwargs: publisher,
    )

    upload_youtube_publication_with_google(
        publication_id=publication_id,
        token_file="/tmp/token.json",
        client_secrets_file="/tmp/client.json",
    )

    result = make_youtube_publication_public_with_google(
        publication_id=publication_id,
        token_file="/tmp/token.json",
        client_secrets_file="/tmp/client.json",
    )

    assert result["status"] == "uploaded"
    assert result["youtube_video_id"] == "youtube123"
    assert result["error"] == "Falha de visibilidade"


def test_make_public_with_google_requires_uploaded_status(
    monkeypatch,
):
    publication_id = _create_publication()

    factory = Mock()

    monkeypatch.setattr(
        "app.services.google_youtube_publication_service."
        "create_google_youtube_publisher",
        factory,
    )

    with pytest.raises(
        ValueError,
        match="not uploaded",
    ):
        make_youtube_publication_public_with_google(
            publication_id=publication_id,
            token_file="/tmp/token.json",
            client_secrets_file="/tmp/client.json",
        )

    factory.assert_not_called()


def test_make_public_with_google_rejects_invalid_publication_id(
    monkeypatch,
):
    factory = Mock()

    monkeypatch.setattr(
        "app.services.google_youtube_publication_service."
        "create_google_youtube_publisher",
        factory,
    )

    with pytest.raises(
        ValueError,
        match="publication_id must be a positive integer",
    ):
        make_youtube_publication_public_with_google(
            publication_id=0,
            token_file="/tmp/token.json",
            client_secrets_file="/tmp/client.json",
        )

    factory.assert_not_called()


def test_process_next_youtube_publication_uploads_only_pending(
    monkeypatch,
):
    publication_id = _create_publication()

    publisher = Mock()
    publisher.upload.return_value = YouTubeUploadResult(
        success=True,
        youtube_video_id="youtube123",
        youtube_url="https://www.youtube.com/watch?v=youtube123",
    )

    monkeypatch.setattr(
        "app.services.google_youtube_publication_service."
        "create_google_youtube_publisher",
        lambda **kwargs: publisher,
    )

    result = process_next_youtube_publication(
        token_file="/tmp/token.json",
        client_secrets_file="/tmp/client.json",
    )

    assert result["id"] == publication_id
    assert result["status"] == "uploaded"
    publisher.upload.assert_called_once()

    persisted = get_youtube_publication(publication_id)

    assert persisted is not None
    assert persisted["status"] == "uploaded"


def test_process_next_youtube_publication_returns_none_when_empty():
    result = process_next_youtube_publication()

    assert result is None


def test_factory_error_propagates(monkeypatch):
    publication_id = _create_publication()

    def failing_factory(**kwargs):
        raise RuntimeError("factory failed")

    monkeypatch.setattr(
        "app.services.google_youtube_publication_service."
        "create_google_youtube_publisher",
        failing_factory,
    )

    with pytest.raises(
        RuntimeError,
        match="factory failed",
    ):
        upload_youtube_publication_with_google(
            publication_id=publication_id,
            token_file="/tmp/token.json",
            client_secrets_file="/tmp/client.json",
        )
