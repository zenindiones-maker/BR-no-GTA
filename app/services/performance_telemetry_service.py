from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any
from uuid import uuid4


_LOCK = threading.Lock()
_SENSITIVE_KEY = re.compile(r"(token|secret|password|api[_-]?key|authorization|credential)", re.I)
_SAFE_TELEMETRY_KEYS = {"model_first_token_ms"}
_CURRENT_TRACE_ID: ContextVar[str | None] = ContextVar("br_perf_trace_id", default=None)
_CURRENT_SPAN_ID: ContextVar[str | None] = ContextVar("br_perf_span_id", default=None)
_CURRENT_LINEAGE: ContextVar[dict[str, str] | None] = ContextVar("br_perf_lineage", default=None)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_trace_id() -> str:
    for key in ("BR_PERFORMANCE_TRACE_ID", "GITHUB_RUN_ID"):
        value = str(os.getenv(key) or "").strip()
        if value:
            attempt = str(os.getenv("GITHUB_RUN_ATTEMPT") or "").strip()
            return f"{value}:{attempt}" if attempt and key == "GITHUB_RUN_ID" else value
    return f"trace-{uuid4().hex}"


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value[:64]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in list(value.items())[:128]:
            key_text = str(key)
            if _SENSITIVE_KEY.search(key_text) and key_text not in _SAFE_TELEMETRY_KEYS:
                continue
            result[key_text] = _safe_value(child)
        return result
    return str(value)[:500]


def current_performance_context() -> dict[str, Any]:
    return {
        "trace_id": _CURRENT_TRACE_ID.get(),
        "span_id": _CURRENT_SPAN_ID.get(),
        "lineage": dict(_CURRENT_LINEAGE.get() or {}),
    }


def emit_performance_event(
    *,
    stage: str,
    category: str,
    started_at: str,
    finished_at: str,
    duration_ms: float,
    queue_wait_ms: float = 0.0,
    provider_wait_ms: float = 0.0,
    network_ms: float = 0.0,
    retry_count: int = 0,
    backoff_ms: float = 0.0,
    attempt_count: int = 1,
    cache_hit: bool | None = None,
    input_size: int | None = None,
    output_size: int | None = None,
    provider: str | None = None,
    model: str | None = None,
    success: bool = True,
    failure_type: str | None = None,
    metadata: dict[str, Any] | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    started_monotonic_ns: int | None = None,
    finished_monotonic_ns: int | None = None,
    goal_id: str | None = None,
    execution_id: str | None = None,
    agent_id: str | None = None,
    capability_id: str | None = None,
    depends_on_span_ids: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    lineage = dict(_CURRENT_LINEAGE.get() or {})
    trace_id = str(trace_id or _CURRENT_TRACE_ID.get() or _default_trace_id())
    span_id = str(span_id or uuid4().hex)
    if parent_span_id is None:
        parent_span_id = _CURRENT_SPAN_ID.get()
    payload = {
        "schema_version": 2,
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "depends_on_span_ids": [str(item) for item in depends_on_span_ids if str(item).strip()],
        "stage": str(stage),
        "category": str(category),
        "started_at": str(started_at),
        "finished_at": str(finished_at),
        "started_monotonic_ns": started_monotonic_ns,
        "finished_monotonic_ns": finished_monotonic_ns,
        "duration_ms": round(max(0.0, float(duration_ms)), 3),
        "queue_wait_ms": round(max(0.0, float(queue_wait_ms)), 3),
        "provider_wait_ms": round(max(0.0, float(provider_wait_ms)), 3),
        "network_ms": round(max(0.0, float(network_ms)), 3),
        "retry_count": max(0, int(retry_count)),
        "backoff_ms": round(max(0.0, float(backoff_ms)), 3),
        "attempt_count": max(1, int(attempt_count)),
        "cache_hit": cache_hit,
        "input_size": None if input_size is None else max(0, int(input_size)),
        "output_size": None if output_size is None else max(0, int(output_size)),
        "provider": provider,
        "model": model,
        "success": bool(success),
        "status": "PASS" if success else "FAIL",
        "failure_type": failure_type,
        "goal_id": goal_id or lineage.get("goal_id"),
        "execution_id": execution_id or lineage.get("execution_id"),
        "agent_id": agent_id or lineage.get("agent_id"),
        "capability_id": capability_id or lineage.get("capability_id"),
        "metadata": _safe_value(metadata or {}),
    }
    trace = str(os.getenv("BR_PERFORMANCE_TRACE_FILE") or "").strip()
    if trace:
        path = Path(trace)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with _LOCK:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
    return payload


class PerformanceSpan:
    def __init__(
        self,
        stage: str,
        category: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        input_size: int | None = None,
        cache_hit: bool | None = None,
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        goal_id: str | None = None,
        execution_id: str | None = None,
        agent_id: str | None = None,
        capability_id: str | None = None,
        depends_on_span_ids: tuple[str, ...] | list[str] = (),
    ) -> None:
        self.stage = stage
        self.category = category
        self.provider = provider
        self.model = model
        self.input_size = input_size
        self.cache_hit = cache_hit
        self.metadata = dict(metadata or {})
        self.explicit_trace_id = trace_id
        self.explicit_parent_span_id = parent_span_id
        self.goal_id = goal_id
        self.execution_id = execution_id
        self.agent_id = agent_id
        self.capability_id = capability_id
        self.depends_on_span_ids = tuple(str(item) for item in depends_on_span_ids if str(item).strip())
        self.started_at = ""
        self.finished_at = ""
        self.started_monotonic_ns = 0
        self.finished_monotonic_ns = 0
        self.trace_id = ""
        self.span_id = uuid4().hex
        self.parent_span_id: str | None = None
        self._trace_token = None
        self._span_token = None
        self._lineage_token = None
        self.values: dict[str, Any] = {}

    def __enter__(self) -> "PerformanceSpan":
        parent_lineage = dict(_CURRENT_LINEAGE.get() or {})
        self.trace_id = str(self.explicit_trace_id or _CURRENT_TRACE_ID.get() or _default_trace_id())
        self.parent_span_id = (
            self.explicit_parent_span_id
            if self.explicit_parent_span_id is not None
            else _CURRENT_SPAN_ID.get()
        )
        lineage = {
            **parent_lineage,
            **{
                key: value
                for key, value in {
                    "goal_id": self.goal_id,
                    "execution_id": self.execution_id,
                    "agent_id": self.agent_id,
                    "capability_id": self.capability_id,
                }.items()
                if value
            },
        }
        self.started_at = utcnow_iso()
        self.started_monotonic_ns = time.perf_counter_ns()
        self._trace_token = _CURRENT_TRACE_ID.set(self.trace_id)
        self._span_token = _CURRENT_SPAN_ID.set(self.span_id)
        self._lineage_token = _CURRENT_LINEAGE.set(lineage)
        return self

    def elapsed_ms(self) -> float:
        if not self.started_monotonic_ns:
            return 0.0
        return (time.perf_counter_ns() - self.started_monotonic_ns) / 1_000_000.0

    def set(self, **values: Any) -> None:
        self.values.update(values)

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.finished_monotonic_ns = time.perf_counter_ns()
        self.finished_at = utcnow_iso()
        duration_ms = (
            self.finished_monotonic_ns - self.started_monotonic_ns
        ) / 1_000_000.0
        success = exc is None
        try:
            emit_performance_event(
                stage=self.stage,
                category=self.category,
                started_at=self.started_at,
                finished_at=self.finished_at,
                started_monotonic_ns=self.started_monotonic_ns,
                finished_monotonic_ns=self.finished_monotonic_ns,
                duration_ms=duration_ms,
                queue_wait_ms=float(self.values.get("queue_wait_ms") or 0.0),
                provider_wait_ms=float(self.values.get("provider_wait_ms") or 0.0),
                network_ms=float(self.values.get("network_ms") or 0.0),
                retry_count=int(self.values.get("retry_count") or 0),
                backoff_ms=float(self.values.get("backoff_ms") or 0.0),
                attempt_count=int(self.values.get("attempt_count") or 1),
                cache_hit=self.values.get("cache_hit", self.cache_hit),
                input_size=self.values.get("input_size", self.input_size),
                output_size=self.values.get("output_size"),
                provider=self.values.get("provider", self.provider),
                model=self.values.get("model", self.model),
                success=success,
                failure_type=(
                    type(exc).__name__ if exc is not None else self.values.get("failure_type")
                ),
                metadata={**self.metadata, **dict(self.values.get("metadata") or {})},
                trace_id=self.trace_id,
                span_id=self.span_id,
                parent_span_id=self.parent_span_id,
                goal_id=self.goal_id,
                execution_id=self.execution_id,
                agent_id=self.agent_id,
                capability_id=self.capability_id,
                depends_on_span_ids=self.depends_on_span_ids,
            )
        finally:
            if self._lineage_token is not None:
                _CURRENT_LINEAGE.reset(self._lineage_token)
            if self._span_token is not None:
                _CURRENT_SPAN_ID.reset(self._span_token)
            if self._trace_token is not None:
                _CURRENT_TRACE_ID.reset(self._trace_token)
        return False
