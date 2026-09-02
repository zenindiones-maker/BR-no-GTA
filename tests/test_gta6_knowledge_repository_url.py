import pytest

from app.database.gta6_knowledge_repository import (
    get_gta6_knowledge_by_source_url,
)


def test_get_gta6_knowledge_by_source_url_requires_url():
    with pytest.raises(ValueError, match="source_url is required"):
        get_gta6_knowledge_by_source_url("")


def test_get_gta6_knowledge_by_source_url_not_found():
    result = get_gta6_knowledge_by_source_url(
        "https://example.com/not-found"
    )

    assert result is None
