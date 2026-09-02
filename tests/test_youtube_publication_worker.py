from unittest.mock import Mock

import pytest

from app.services.youtube_publication_worker import (
    execute_youtube_publication,
)


def test_execute_youtube_publication_delegates_to_orchestration(
    monkeypatch,
):
    publisher = Mock()

    expected = {
        "id": 42,
        "status": "published",
    }

    orchestration = Mock(
        return_value=expected,
    )

    monkeypatch.setattr(
        "app.services.youtube_publication_worker.publish_youtube_publication",
        orchestration,
    )

    result = execute_youtube_publication(
        publication_id=42,
        publisher=publisher,
    )

    assert result == expected

    orchestration.assert_called_once_with(
        publication_id=42,
        publisher=publisher,
    )


def test_execute_youtube_publication_rejects_invalid_publication_id():
    with pytest.raises(ValueError, match="publication_id"):
        execute_youtube_publication(
            publication_id=0,
            publisher=Mock(),
        )


def test_execute_youtube_publication_rejects_missing_publisher():
    with pytest.raises(ValueError, match="publisher"):
        execute_youtube_publication(
            publication_id=1,
            publisher=None,
        )
