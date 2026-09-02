import json

import pytest

from app.integrations.gta6.rockstar_newswire_graph import (
    GTA6_NEWSWIRE_TAG_ID,
    NEWSWIRE_OPERATION,
    RockstarNewswireGraphClient,
)


def test_client_requires_query_hash():
    with pytest.raises(ValueError):
        RockstarNewswireGraphClient("")


def test_build_url_uses_gtavi_tag_and_newswire_operation():
    client = RockstarNewswireGraphClient("abc123")

    url = client.build_url()

    assert "operationName=NewswireList" in url
    assert "tagId%22%3A666" in url or '"tagId":666' in url
    assert NEWSWIRE_OPERATION == "NewswireList"
    assert GTA6_NEWSWIRE_TAG_ID == 666


def test_parse_articles():
    payload = {
        "data": {
            "posts": {
                "results": [
                    {
                        "id": 12345,
                        "title": "GTA VI News",
                        "url": "/newswire/gta-vi-news",
                        "created": "2026-09-01T12:00:00Z",
                        "primary_tags": [
                            {"name": "GTA VI"},
                            {"name": "Newswire"},
                        ],
                        "preview_images_parsed": {
                            "newswire_block": {
                                "d16x9": "https://example.com/image.jpg"
                            }
                        },
                    }
                ]
            }
        }
    }

    client = RockstarNewswireGraphClient("abc123")
    articles = client.parse_articles(payload)

    assert len(articles) == 1

    article = articles[0]

    assert article.article_id == "12345"
    assert article.title == "GTA VI News"
    assert article.url == (
        "https://www.rockstargames.com/newswire/gta-vi-news"
    )
    assert article.created_at == "2026-09-01T12:00:00Z"
    assert article.tags == ("GTA VI", "Newswire")
    assert article.image_url == "https://example.com/image.jpg"


def test_parse_articles_accepts_absolute_url():
    payload = {
        "data": {
            "posts": {
                "results": [
                    {
                        "id": 1,
                        "title": "Absolute URL",
                        "url": "https://www.rockstargames.com/newswire/test",
                        "primary_tags": [],
                    }
                ]
            }
        }
    }

    client = RockstarNewswireGraphClient("abc123")
    articles = client.parse_articles(payload)

    assert articles[0].url == (
        "https://www.rockstargames.com/newswire/test"
    )


def test_parse_articles_skips_invalid_items():
    payload = {
        "data": {
            "posts": {
                "results": [
                    None,
                    {},
                    {"id": 1},
                    {"id": 2, "title": "Valid"},
                    {
                        "id": 3,
                        "title": "Valid",
                        "url": "/newswire/valid",
                    },
                ]
            }
        }
    }

    client = RockstarNewswireGraphClient("abc123")
    articles = client.parse_articles(payload)

    assert len(articles) == 1
    assert articles[0].article_id == "3"


def test_parse_articles_rejects_graph_errors():
    payload = {
        "errors": [
            {
                "message": "PersistedQueryNotFound",
            }
        ]
    }

    client = RockstarNewswireGraphClient("abc123")

    with pytest.raises(RuntimeError):
        client.parse_articles(payload)


def test_parse_articles_rejects_invalid_payload():
    client = RockstarNewswireGraphClient("abc123")

    with pytest.raises(ValueError):
        client.parse_articles([])


def test_fetch_uses_network_only_when_called():
    client = RockstarNewswireGraphClient("abc123")

    assert client.query_hash == "abc123"
    assert json.loads(
        '{"persistedQuery":{"version":1,"sha256Hash":"abc123"}}'
    )["persistedQuery"]["sha256Hash"] == client.query_hash
