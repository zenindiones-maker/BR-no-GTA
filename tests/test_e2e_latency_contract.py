from app.services.performance_telemetry_service import emit_performance_event

def test_performance_event_exposes_latency_work_contract(monkeypatch):
    monkeypatch.delenv("BR_PERFORMANCE_TRACE_FILE", raising=False)
    event=emit_performance_event(
        stage="render_wait",
        category="WAITING_EXTERNAL_TIME",
        started_at="2026-09-19T00:00:00+00:00",
        finished_at="2026-09-19T00:00:01+00:00",
        duration_ms=1000,
        work_class="WAITING",
        attempt=2,
        cache_hit=True,
        input_fingerprint="abc",
        output_artifact="render-watch.json",
    )
    assert event["start"]==event["started_at"]
    assert event["end"]==event["finished_at"]
    assert event["work_class"]=="WAITING"
    assert event["attempt"]==2
    assert event["cache_hit"] is True
    assert event["input_fingerprint"]=="abc"
    assert event["output_artifact"]=="render-watch.json"
