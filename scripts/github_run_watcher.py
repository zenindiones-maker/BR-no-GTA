from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import urllib.request
from typing import Any


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _get_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "BR-no-GTA-run-watcher/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def watch_run(
    *,
    repo: str,
    run_id: int,
    token: str,
    min_interval: float = 2.0,
    max_interval: float = 20.0,
    timeout_seconds: float = 3600.0,
) -> dict[str, Any]:
    run_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"
    started = time.perf_counter()
    deadline = started + timeout_seconds
    interval = max(1.0, min_interval)
    poll_count = 0
    redundant = 0
    previous_marker = None

    while True:
        if time.perf_counter() > deadline:
            raise TimeoutError(f"run watcher timed out: {run_id}")
        payload = _get_json(run_url, token)
        poll_count += 1
        marker = (payload.get("status"), payload.get("conclusion"), payload.get("updated_at"))
        if marker == previous_marker:
            redundant += 1
        previous_marker = marker
        if payload.get("status") == "completed":
            break
        time.sleep(interval)
        interval = min(max_interval, interval * 1.7)

    jobs_payload = _get_json(f"{run_url}/jobs?per_page=100", token)
    jobs = list(jobs_payload.get("jobs") or ())
    failed_job = next((job for job in jobs if job.get("conclusion") == "failure"), None)
    failed_step = None
    if failed_job:
        failed_step = next(
            (step for step in failed_job.get("steps") or () if step.get("conclusion") == "failure"),
            None,
        )

    detected_at = datetime.now(timezone.utc)
    completed = [_parse_time(job.get("completed_at")) for job in jobs]
    completed = [item for item in completed if item is not None]
    completed_at = max(completed) if completed else _parse_time(payload.get("updated_at"))
    detection_delay_ms = (
        max(0.0, (detected_at - completed_at).total_seconds() * 1000.0)
        if completed_at is not None
        else None
    )

    return {
        "status": "PASS",
        "run_id": run_id,
        "run_status": payload.get("status"),
        "run_conclusion": payload.get("conclusion"),
        "GITHUB_POLL_COUNT": poll_count,
        "GITHUB_POLL_TOTAL_MS": round((time.perf_counter() - started) * 1000.0, 3),
        "GITHUB_REDUNDANT_POLL_COUNT": redundant,
        "COMPLETION_DETECTION_DELAY_MS": (
            None if detection_delay_ms is None else round(detection_delay_ms, 3)
        ),
        "failed_job_id": None if failed_job is None else failed_job.get("id"),
        "failed_job_name": None if failed_job is None else failed_job.get("name"),
        "failed_step": failed_step,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-interval", type=float, default=2.0)
    parser.add_argument("--max-interval", type=float, default=20.0)
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    args = parser.parse_args()

    token = str(os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("GH_TOKEN or GITHUB_TOKEN is required")
    if args.repo.count("/") != 1:
        raise RuntimeError("--repo must be owner/name")

    result = watch_run(
        repo=args.repo,
        run_id=args.run_id,
        token=token,
        min_interval=args.min_interval,
        max_interval=args.max_interval,
        timeout_seconds=args.timeout_seconds,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for key in (
        "GITHUB_POLL_COUNT",
        "GITHUB_POLL_TOTAL_MS",
        "GITHUB_REDUNDANT_POLL_COUNT",
        "COMPLETION_DETECTION_DELAY_MS",
    ):
        print(f"{key}={result[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
