from app.services import gta6_research_pipeline as module


def test_run_gta6_research_ingests_rockstar_monitor_and_graph(
    monkeypatch,
):
    monitor_result = {"changed": True}

    monitor_items = [
        {
            "research_item_id": 1,
            "knowledge_id": 1,
            "knowledge": None,
            "duplicate": False,
        }
    ]

    graph_items = [
        {
            "research_item_id": 2,
            "knowledge_id": 2,
            "knowledge": None,
            "duplicate": True,
        }
    ]

    news_items = [{"title": "News item"}]
    editorial_result = [{"idea_id": 1, "decision": "approve"}]
    calls = []
    editorial_calls = []

    monkeypatch.setattr(
        module,
        "monitor_rockstar_newswire",
        lambda: monitor_result,
    )

    monkeypatch.setattr(
        module,
        "ingest_rockstar_newswire_from_monitor",
        lambda: monitor_items.copy(),
    )

    monkeypatch.setattr(
        module.settings,
        "ROCKSTAR_QUERY_HASH",
        "test-query-hash",
    )

    def fake_graph_ingestion(query_hash):
        calls.append(query_hash)
        return graph_items

    monkeypatch.setattr(
        module,
        "ingest_rockstar_newswire",
        fake_graph_ingestion,
    )

    monkeypatch.setattr(
        module,
        "run_gta6_news_pipeline",
        lambda: news_items,
    )

    def fake_editorial_processing(results):
        editorial_calls.append(results)
        return editorial_result

    monkeypatch.setattr(
        module,
        "process_gta6_research_results",
        fake_editorial_processing,
    )

    result = module.run_gta6_research()

    assert calls == ["test-query-hash"]

    assert result["rockstar_monitor"] == monitor_result
    assert result["rockstar_newswire"] == monitor_items + graph_items
    assert result["news_feeds"] == news_items
    assert result["total"] == 3

    assert editorial_calls == [
        monitor_items + graph_items + news_items
    ]

    assert result["editorial"] == editorial_result


def test_run_gta6_research_does_not_call_graph_without_query_hash(
    monkeypatch,
):
    monitor_result = {"changed": False}
    monitor_items = []
    editorial_calls = []

    monkeypatch.setattr(
        module,
        "monitor_rockstar_newswire",
        lambda: monitor_result,
    )

    monkeypatch.setattr(
        module,
        "ingest_rockstar_newswire_from_monitor",
        lambda: monitor_items,
    )

    monkeypatch.setattr(
        module.settings,
        "ROCKSTAR_QUERY_HASH",
        None,
    )

    def fail_if_called(query_hash):
        raise AssertionError(
            "Graph ingestion should not be called without query hash"
        )

    monkeypatch.setattr(
        module,
        "ingest_rockstar_newswire",
        fail_if_called,
    )

    monkeypatch.setattr(
        module,
        "run_gta6_news_pipeline",
        lambda: [],
    )

    monkeypatch.setattr(
        module,
        "process_gta6_research_results",
        lambda results: editorial_calls.append(results) or [],
    )

    result = module.run_gta6_research()

    assert result["rockstar_newswire"] == []
    assert result["total"] == 0
    assert editorial_calls == [[]]
    assert result["editorial"] == []
