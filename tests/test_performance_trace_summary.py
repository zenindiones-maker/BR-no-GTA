from scripts.summarize_performance_trace import _span_metrics


def _event(
    *,
    span_id: str,
    parent_span_id: str | None,
    start: str,
    end: str,
    duration_ms: float,
    provider: str | None = None,
):
    return {
        "schema_version": 2,
        "trace_id": "trace-test",
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "stage": span_id,
        "category": "AI_PROVIDER_TIME" if provider else "CONTROL_PLANE_TIME",
        "started_at": start,
        "finished_at": end,
        "duration_ms": duration_ms,
        "provider": provider,
    }


def test_parallel_spans_do_not_inflate_critical_path():
    events = [
        _event(
            span_id="parent",
            parent_span_id=None,
            start="2026-09-19T00:00:00+00:00",
            end="2026-09-19T00:00:01+00:00",
            duration_ms=1000,
        ),
        _event(
            span_id="a",
            parent_span_id="parent",
            start="2026-09-19T00:00:00+00:00",
            end="2026-09-19T00:00:00.800000+00:00",
            duration_ms=800,
            provider="opencode",
        ),
        _event(
            span_id="b",
            parent_span_id="parent",
            start="2026-09-19T00:00:00.200000+00:00",
            end="2026-09-19T00:00:01+00:00",
            duration_ms=800,
            provider="opencode",
        ),
    ]
    spans, metrics = _span_metrics(events)
    by_id = {span["span_id"]: span for span in spans}
    assert by_id["parent"]["inclusive_ms"] == 1000
    assert by_id["parent"]["exclusive_ms"] == 0
    assert metrics["trace_active_wall_ms"] == 1000
    assert metrics["trace_cumulative_work_ms"] == 1600
    assert metrics["parallelism_saved_ms"] == 600
    assert metrics["provider_critical_path_ms"] == 1000
    assert metrics["provider_cumulative_work_ms"] == 1600


def test_self_parent_is_not_counted_as_child_work():
    events = [
        _event(
            span_id="root",
            parent_span_id="root",
            start="2026-09-19T00:00:00+00:00",
            end="2026-09-19T00:00:01+00:00",
            duration_ms=1000,
        )
    ]
    spans, metrics = _span_metrics(events)
    assert spans[0]["exclusive_ms"] == 1000
    assert metrics["trace_cumulative_work_ms"] == 1000
