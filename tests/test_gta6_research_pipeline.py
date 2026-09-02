from app.services.gta6_research_pipeline import run_gta6_research


def test_run_gta6_research(monkeypatch):
    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.ingest_rockstar_newswire",
        lambda: [{"knowledge_id": 1}],
    )
    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.run_gta6_news_pipeline",
        lambda: [{"knowledge_id": 2}, {"knowledge_id": 3}],
    )

    result = run_gta6_research()

    assert result == {
        "rockstar_newswire": [{"knowledge_id": 1}],
        "news_feeds": [
            {"knowledge_id": 2},
            {"knowledge_id": 3},
        ],
        "total": 3,
    }


def test_run_gta6_research_empty(monkeypatch):
    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.ingest_rockstar_newswire",
        lambda: [],
    )
    monkeypatch.setattr(
        "app.services.gta6_research_pipeline.run_gta6_news_pipeline",
        lambda: [],
    )

    result = run_gta6_research()

    assert result == {
        "rockstar_newswire": [],
        "news_feeds": [],
        "total": 0,
    }
