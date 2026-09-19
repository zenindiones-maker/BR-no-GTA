from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any


_LOCK = threading.Lock()
_SENSITIVE_KEY = re.compile(r"(token|secret|password|api[_-]?key|authorization|credential)", re.I)
_SAFE_TELEMETRY_KEYS = {"model_first_token_ms"}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "stage": str(stage),
        "category": str(category),
        "started_at": str(started_at),
        "finished_at": str(finished_at),
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
        "failure_type": failure_type,
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
    ) -> None:
        self.stage = stage
        self.category = category
        self.provider = provider
        self.model = model
        self.input_size = input_size
        self.cache_hit = cache_hit
        self.metadata = dict(metadata or {})
        self.started_at = ""
        self.finished_at = ""
        self._started_ns = 0
        self.values: dict[str, Any] = {}

    def __enter__(self) -> "PerformanceSpan":
        self.started_at = utcnow_iso()
        self._started_ns = time.perf_counter_ns()
        return self

    def elapsed_ms(self) -> float:
        if not self._started_ns:
            return 0.0
        return (time.perf_counter_ns() - self._started_ns) / 1_000_000.0

    def set(self, **values: Any) -> None:
        self.values.update(values)

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.finished_at = utcnow_iso()
        duration_ms = self.elapsed_ms()
        success = exc is None
        emit_performance_event(
            stage=self.stage,
            category=self.category,
            started_at=self.started_at,
            finished_at=self.finished_at,
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
            failure_type=(type(exc).__name__ if exc is not None else self.values.get("failure_type")),
            metadata={**self.metadata, **dict(self.values.get("metadata") or {})},
        )
        return False
