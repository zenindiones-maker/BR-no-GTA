from app.services.gta6_research_pipeline import run_gta6_research


def test_run_gta6_research_runs_rockstar_monitor(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.monitor_rockstar_newswire",
        lambda: calls.append(True) or "monitor-result",
    )
    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.run_gta6_news_pipeline",
        lambda: [],
    )

    result = run_gta6_research()

    assert calls == [True]
    assert result["rockstar_monitor"] == "monitor-result"


def test_run_gta6_research(monkeypatch):
    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.monitor_rockstar_newswire",
        lambda: "monitor-result",
    )
    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.settings.ROCKSTAR_QUERY_HASH",
        "test-query-hash",
    )
    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.ingest_rockstar_newswire",
        lambda query_hash: [{"knowledge_id": 1}],
    )
    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.run_gta6_news_pipeline",
        lambda: [{"knowledge_id": 2}, {"knowledge_id": 3}],
    )

    result = run_gta6_research()

    assert result == {
        "rockstar_monitor": "monitor-result",
        "rockstar_newswire": [{"knowledge_id": 1}],
        "news_feeds": [
            {"knowledge_id": 2},
            {"knowledge_id": 3},
        ],
        "total": 3,
    }


def test_run_gta6_research_without_rockstar_query_hash(monkeypatch):
    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.monitor_rockstar_newswire",
        lambda: "monitor-result",
    )
    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.settings.ROCKSTAR_QUERY_HASH",
        None,
    )

    def fail_if_called(query_hash):
        raise AssertionError(
            "Rockstar Graph ingestion should not run without query hash"
        )

    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.ingest_rockstar_newswire",
        fail_if_called,
    )
    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.run_gta6_news_pipeline",
        lambda: [{"knowledge_id": 2}],
    )

    result = run_gta6_research()

    assert result == {
        "rockstar_monitor": "monitor-result",
        "rockstar_newswire": [],
        "news_feeds": [{"knowledge_id": 2}],
        "total": 1,
    }


def test_run_gta6_research_empty(monkeypatch):
    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.monitor_rockstar_newswire",
        lambda: "monitor-result",
    )
    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.settings.ROCKSTAR_QUERY_HASH",
        "test-query-hash",
    )
    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.ingest_rockstar_newswire",
        lambda query_hash: [],
    )
    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.run_gta6_news_pipeline",
        lambda: [],
    )

    result = run_gta6_research()

    assert result == {
        "rockstar_monitor": "monitor-result",
        "rockstar_newswire": [],
        "news_feeds": [],
        "total": 0,
    }
