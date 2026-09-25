from app.services import gta6_research_pipeline as module
from app.services.harness_authorization_service import (
    authorization_to_context,
    issue_harness_authorization,
)


def _research_context():
    return authorization_to_context(
        issue_harness_authorization(
            authorized_action="RESEARCH",
            subject="action:RESEARCH",
        )
    )


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
        lambda **kwargs: (
            monitor_items.copy()
            if kwargs.get("monitored_result") is monitor_result
            else (_ for _ in ()).throw(AssertionError("monitor result not reused"))
        ),
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
    monkeypatch.setattr(
        module,
        "get_research_item",
        lambda item_id: {
            "id": item_id,
            "title": "Official GTA VI update",
            "content": "Official Rockstar source details.",
            "url": "https://www.rockstargames.com/newswire/article/test",
        } if item_id in {1, 2} else None,
    )

    result = module.run_gta6_research(_research_context())

    assert calls == ["test-query-hash"]

    assert result["rockstar_monitor"] == monitor_result
    assert result["rockstar_newswire"] == monitor_items + graph_items
    assert result["news_feeds"] == news_items
    assert [item["id"] for item in result["official_research_items"]] == [1, 2]
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
        lambda **_kwargs: monitor_items,
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
    monkeypatch.setattr(module, "get_research_item", lambda _item_id: None)

    result = module.run_gta6_research(_research_context())

    assert result["rockstar_newswire"] == []
    assert result["total"] == 0
    assert editorial_calls == [[]]
    assert result["editorial"] == []


def test_run_gta6_research_requires_persisted_harness_authorization():
    import pytest

    with pytest.raises(PermissionError):
        module.run_gta6_research()


def test_run_gta6_research_rejects_wrong_action():
    import pytest

    context = authorization_to_context(
        issue_harness_authorization(
            authorized_action="EXECUTION",
            subject="action:EXECUTION",
        )
    )

    with pytest.raises(PermissionError):
        module.run_gta6_research(context)


def test_run_gta6_research_rejects_execution_id_mismatch():
    import pytest

    context = _research_context()
    context["execution_id"] = "mismatched-execution-id"

    with pytest.raises(PermissionError, match="execution_id mismatch"):
        module.run_gta6_research(context)

def test_run_gta6_research_routes_monitor_transport_failure_through_governed_acquisition(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        module,
        "monitor_rockstar_newswire",
        lambda **kwargs: (
            calls.append(("monitor", kwargs))
            or ({"changed": False} if kwargs else (_ for _ in ()).throw(RuntimeError("302 loop")))
        ),
    )
    monkeypatch.setattr(
        module,
        "execute_web_source_acquire",
        lambda **kwargs: calls.append(("acquire", kwargs)) or {
            "status": "EXECUTED",
            "source_url": module.ROCKSTAR_NEWSWIRE_URL,
            "content": "<html>official</html>",
            "provenance": {
                "source_url": module.ROCKSTAR_NEWSWIRE_URL,
                "transport_provider": "apilayer_scraper",
            },
        },
    )
    monkeypatch.setattr(
        module,
        "ingest_rockstar_newswire_from_monitor",
        lambda **kwargs: (
            calls.append(("ingest", kwargs))
            or []
        ),
    )
    monkeypatch.setattr(module.settings, "ROCKSTAR_QUERY_HASH", None)
    monkeypatch.setattr(module, "run_gta6_news_pipeline", lambda: [])
    monkeypatch.setattr(module, "process_gta6_research_results", lambda _results: [])
    monkeypatch.setattr(module, "get_research_item", lambda _item_id: None)

    result = module.run_gta6_research(_research_context())

    assert [name for name, _ in calls] == ["monitor", "acquire", "monitor", "ingest"]
    acquisition = calls[1][1]
    assert acquisition["payload"]["source_url"] == module.ROCKSTAR_NEWSWIRE_URL
    assert acquisition["routing_decision"].selected_capability_id == module.WEB_SOURCE_ACQUIRE
    assert calls[3][1]["monitored_result"] == {"changed": False}
    assert result["rockstar_monitor"] == {"changed": False}
