from app.integrations.gta6.rockstar_newswire_graph import (
    RockstarNewswireGraphClient,
)
from app.integrations.gta6.rockstar_newswire_source import (
    fetch_rockstar_newswire_source,
)


def test_fetch_rockstar_newswire_source(monkeypatch):
    payload = {
        "data": {
            "posts": {
                "results": [
                    {
                        "id": 123,
                        "title": "GTA VI News",
                        "url": "/newswire/gta-vi-news",
                        "created": "2026-09-01T12:00:00Z",
                        "primary_tags": [],
                    }
                ]
            }
        }
    }

    client = RockstarNewswireGraphClient("abc123")

    monkeypatch.setattr(
        client,
        "fetch",
        lambda: payload,
    )

    items = fetch_rockstar_newswire_source(client)

    assert len(items) == 1
    assert items[0].title == "GTA VI News"
    assert items[0].source_name == "Rockstar Newswire"
    assert items[0].confidence == "confirmed"
    assert items[0].fact_type == "news"
    assert items[0].url == (
        "https://www.rockstargames.com/newswire/gta-vi-news"
    )


def test_fetch_rockstar_newswire_source_does_not_fetch_during_construction(
    monkeypatch,
):
    called = False

    def fail_fetch():
        nonlocal called
        called = True
        raise AssertionError("network must not run here")

    client = RockstarNewswireGraphClient("abc123")
    monkeypatch.setattr(client, "fetch", fail_fetch)

    assert called is False
    assert client.query_hash == "abc123"
