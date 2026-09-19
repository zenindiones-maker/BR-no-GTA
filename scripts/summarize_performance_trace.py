from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import urllib.request
from typing import Any


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _duration_ms(started: str | None, finished: str | None) -> float | None:
    a = _parse_time(started)
    b = _parse_time(finished)
    if a is None:
        return None
    if b is None:
        b = datetime.now(timezone.utc)
    return max(0.0, (b - a).total_seconds() * 1000.0)


def _github_steps(run_id: str) -> dict[str, Any]:
    token = str(os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    repo = str(os.getenv("GITHUB_REPOSITORY") or "").strip()
    if not token or repo.count("/") != 1 or not run_id:
        return {"available": False, "steps": []}
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs?per_page=100"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "BR-no-GTA-performance/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"available": False, "error": type(exc).__name__, "steps": []}
    jobs = list(payload.get("jobs") or ())
    if not jobs:
        return {"available": False, "steps": []}
    job = jobs[0]
    steps = []
    for step in job.get("steps") or ():
        steps.append({
            "name": step.get("name"),
            "status": step.get("status"),
            "conclusion": step.get("conclusion"),
            "started_at": step.get("started_at"),
            "completed_at": step.get("completed_at"),
            "duration_ms": _duration_ms(step.get("started_at"), step.get("completed_at")),
        })
    return {
        "available": True,
        "job_id": job.get("id"),
        "job_started_at": job.get("started_at"),
        "job_completed_at": job.get("completed_at"),
        "job_elapsed_ms": _duration_ms(job.get("started_at"), job.get("completed_at")),
        "steps": steps,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", ""))
    args = parser.parse_args()

    events: list[dict[str, Any]] = []
    if args.trace.is_file():
        for raw in args.trace.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                value = json.loads(raw)
                if isinstance(value, dict):
                    events.append(value)

    category_ms: dict[str, float] = defaultdict(float)
    retry_ms = 0.0
    provider_total_ms = 0.0
    for event in events:
        category_ms[str(event.get("category") or "IDLE/UNKNOWN_TIME")] += float(event.get("duration_ms") or 0.0)
        retry_ms += float(event.get("backoff_ms") or 0.0)
        if event.get("category") == "AI_PROVIDER_TIME":
            provider_total_ms += float(event.get("duration_ms") or 0.0)

    slowest = sorted(events, key=lambda item: float(item.get("duration_ms") or 0.0), reverse=True)[:20]
    provider_calls = [
        {
            "stage": event.get("stage"),
            "duration_ms": event.get("duration_ms"),
            "provider": event.get("provider"),
            "model": event.get("model"),
            "success": event.get("success"),
            "failure_type": event.get("failure_type"),
            **{
                key: (event.get("metadata") or {}).get(key)
                for key in (
                    "cli_process_launch_ms",
                    "cli_process_startup_ms",
                    "model_first_token_ms",
                    "model_total_ms",
                    "json_parse_ms",
                    "process_teardown_ms",
                    "event_count",
                    "tool_call_count",
                    "parse_errors",
                )
            },
        }
        for event in events
        if event.get("category") == "AI_PROVIDER_TIME" and event.get("stage") == "opencode.semantic.generate"
    ]

    report = {
        "schema_version": 1,
        "status": "PASS",
        "run_id": args.run_id or None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "event_count": len(events),
        "category_totals_ms": dict(sorted(category_ms.items())),
        "retry_time_ms": retry_ms,
        "provider_time_ms": provider_total_ms,
        "slowest_stages": slowest,
        "provider_calls": provider_calls,
        "github_actions": _github_steps(str(args.run_id or "")),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PERF_EVENT_COUNT={len(events)}")
    print(f"PROVIDER_TIME_MS={provider_total_ms:.3f}")
    print(f"RETRY_TIME_MS={retry_ms:.3f}")
    if slowest:
        print(f"SLOWEST_STAGE={slowest[0].get('stage')}")
        print(f"SLOWEST_STAGE_MS={float(slowest[0].get('duration_ms') or 0.0):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
