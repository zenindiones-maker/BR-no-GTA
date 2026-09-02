from app.services import gta6_source_ingestion


def test_ingest_rockstar_newswire_uses_graph_source(monkeypatch):
    calls = {}

    class FakeClient:
        def __init__(self, query_hash):
            calls["query_hash"] = query_hash

    def fake_fetch(client):
        calls["client"] = client
        return [{"title": "GTA VI News"}]

    def fake_ingest(items):
        calls["items"] = items
        return [{"knowledge_id": 1, "duplicate": False}]

    monkeypatch.setattr(
        gta6_source_ingestion,
        "RockstarNewswireGraphClient",
        FakeClient,
    )
    monkeypatch.setattr(
        gta6_source_ingestion,
        "fetch_rockstar_newswire_source",
        fake_fetch,
    )
    monkeypatch.setattr(
        gta6_source_ingestion,
        "ingest_gta6_source_items",
        fake_ingest,
    )

    result = gta6_source_ingestion.ingest_rockstar_newswire(
        "test-query-hash"
    )

    assert calls["query_hash"] == "test-query-hash"
    assert calls["client"].__class__ is FakeClient
    assert calls["items"] == [{"title": "GTA VI News"}]
    assert result == [{"knowledge_id": 1, "duplicate": False}]


def test_ingest_rockstar_newswire_returns_empty_without_items(monkeypatch):
    class FakeClient:
        def __init__(self, query_hash):
            pass

    monkeypatch.setattr(
        gta6_source_ingestion,
        "RockstarNewswireGraphClient",
        FakeClient,
    )
    monkeypatch.setattr(
        gta6_source_ingestion,
        "fetch_rockstar_newswire_source",
        lambda client: [],
    )

    result = gta6_source_ingestion.ingest_rockstar_newswire(
        "test-query-hash"
    )

    assert result == []
