from unittest.mock import Mock

from app.services.youtube_publication_runner import (
    run_google_youtube_publication,
)


def test_run_google_youtube_publication_composes_factory_and_worker(
    monkeypatch,
):
    publisher = Mock()
    expected = {
        "id": 7,
        "status": "published",
    }

    factory = Mock(
        return_value=publisher,
    )

    worker = Mock(
        return_value=expected,
    )

    monkeypatch.setattr(
        "app.services.youtube_publication_runner.create_google_youtube_publisher",
        factory,
    )

    monkeypatch.setattr(
        "app.services.youtube_publication_runner.execute_youtube_publication",
        worker,
    )

    result = run_google_youtube_publication(
        publication_id=7,
        token_file="/tmp/token.json",
        client_secrets_file="/tmp/client_secret.json",
    )

    assert result == expected

    factory.assert_called_once_with(
        token_file="/tmp/token.json",
        client_secrets_file="/tmp/client_secret.json",
    )

    worker.assert_called_once_with(
        publication_id=7,
        publisher=publisher,
    )
