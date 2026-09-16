from types import SimpleNamespace

import pytest

from app.services import youtube_analytics_learning_service as svc
from app.services.harness_capability_service import CapabilityExecutionBlocked


def source():
    return {
        "source": "youtube_analytics",
        "capability_id": "youtube.analytics.read",
        "publication_id": 7,
        "youtube_video_id": "persisted-video",
        "metric_window": {"start_date": "2026-09-01", "end_date": "2026-09-02"},
        "retrieved_at": "2026-09-03T00:00:00Z",
        "execution_id": "source-exec",
        "authorization_id": "source-auth",
        "metrics": {name: {"status": "MISSING", "value": None} for name in svc.METRICS},
    }


def cap():
    return SimpleNamespace(capability_id=svc.CAPABILITY_ID, executor_binding=svc.EXECUTOR_BINDING)


def test_zero_missing_and_idempotency(monkeypatch):
    evidence = source()
    evidence["metrics"]["views"] = {"status": "VALUE", "value": 0}
    stored = []
    monkeypatch.setattr(svc, "list_memory_events_by_source", lambda **kw: stored)
    monkeypatch.setattr(svc, "insert_memory_event", lambda event: stored.append({"id": 11, **event.__dict__}) or 11)
    assert svc.execute_youtube_analytics_learning_capability(cap(), evidence)["status"] == "LEARNED"
    assert svc.execute_youtube_analytics_learning_capability(cap(), evidence)["status"] == "ALREADY_LEARNED"
    assert len(stored) == 1
    metadata = stored[0]["metadata"]
    assert metadata["metrics"]["views"] == {"status": "VALUE", "value": 0}
    assert metadata["metrics"]["likes"] == {"status": "MISSING", "value": None}
    assert metadata["publication_id"] == 7
    assert metadata["youtube_video_id"] == "persisted-video"
    assert metadata["metric_window"] == {"start_date": "2026-09-01", "end_date": "2026-09-02"}


def test_accepts_exact_metric_window_emitted_by_analytics_service(monkeypatch):
    evidence = source()
    stored = []
    monkeypatch.setattr(svc, "list_memory_events_by_source", lambda **kw: stored)
    monkeypatch.setattr(svc, "insert_memory_event", lambda event: 17)

    result = svc.execute_youtube_analytics_learning_capability(cap(), evidence)

    assert result["status"] == "LEARNED"
    assert result["learning"]["metric_window"] == {
        "start_date": "2026-09-01",
        "end_date": "2026-09-02",
    }


def test_legacy_or_ambiguous_metric_window_fails_closed():
    evidence = source()
    evidence["metric_window"] = {"start": "2026-09-01", "end": "2026-09-02"}
    with pytest.raises(CapabilityExecutionBlocked):
        svc.execute_youtube_analytics_learning_capability(cap(), evidence)

    evidence = source()
    evidence["metric_window"]["start"] = evidence["metric_window"]["start_date"]
    with pytest.raises(CapabilityExecutionBlocked):
        svc.execute_youtube_analytics_learning_capability(cap(), evidence)


def test_requires_persisted_video():
    evidence = source()
    evidence["youtube_video_id"] = ""
    with pytest.raises(CapabilityExecutionBlocked):
        svc.execute_youtube_analytics_learning_capability(cap(), evidence)


def test_wrong_binding_fails_closed():
    with pytest.raises(CapabilityExecutionBlocked):
        svc.execute_youtube_analytics_learning_capability(SimpleNamespace(capability_id=svc.CAPABILITY_ID, executor_binding="evil"), source())
