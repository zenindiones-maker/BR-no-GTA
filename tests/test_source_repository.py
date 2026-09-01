import pytest

from app.database.schema import initialize_schema
from app.database.source_repository import (
    get_source,
    insert_source,
    list_sources,
)


def test_insert_and_get_source():
    initialize_schema()

    source_id = insert_source(
        name="TEST SOURCE",
        url="https://example.com",
        source_type="website",
    )

    assert isinstance(source_id, int)
    assert source_id > 0

    source = get_source(source_id)

    assert source is not None
    assert source["id"] == source_id
    assert source["name"] == "TEST SOURCE"
    assert source["url"] == "https://example.com"
    assert source["source_type"] == "website"


def test_list_sources():
    initialize_schema()

    first_id = insert_source(
        name="TEST SOURCE 1",
        url="https://example.com/1",
        source_type="website",
    )

    second_id = insert_source(
        name="TEST SOURCE 2",
        url="https://example.com/2",
        source_type="platform",
    )

    sources = list_sources()

    ids = {source["id"] for source in sources}

    assert first_id in ids
    assert second_id in ids


def test_get_nonexistent_source():
    initialize_schema()

    assert get_source(999999) is None
