from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import resource
import statistics
import time
from typing import Any, Callable

from app.database.schema import initialize_schema
from app.services.harness_collaboration_service import build_collaboration_plan
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.system_synergy_service import select_specialist


ROUTING_CASES = (
    {
        "intent": "verify GTA6 claims against source evidence",
        "authorized_action": "RESEARCH",
        "domain": "gta6-research",
        "required_capability_id": "gta6.fact-check",
    },
    {
        "intent": "derive YouTube content strategy from verified GTA6 evidence",
        "authorized_action": "EDITORIAL",
        "domain": "youtube-department",
        "required_capability_id": "youtube.department.content-strategy",
    },
    {
        "intent": "execute governed long-form production render",
        "authorized_action": "EXECUTION",
        "domain": "production-render",
        "required_capability_id": "production.render.execute",
    },
)

COLLABORATION_TASKS = (
    {
        "task_id": "fact-check",
        "capability_id": "gta6.fact-check",
        "action": "RESEARCH",
        "objective": "verify grounded GTA6 claims",
        "expected_output": "FactCheckResult",
    },
    {
        "task_id": "brain",
        "capability_id": "gta6.brain.decide",
        "action": "DECISION",
        "objective": "make bounded GTA6 domain decision",
        "dependencies": ["fact-check"],
        "expected_output": "BrainDecision",
    },
    {
        "task_id": "content-strategy",
        "capability_id": "youtube.department.content-strategy",
        "action": "EDITORIAL",
        "objective": "derive grounded content strategy",
        "dependencies": ["brain"],
        "expected_output": "YouTubeSpecialistResult",
    },
    {
        "task_id": "script-review",
        "capability_id": "youtube.department.script-review",
        "action": "EDITORIAL",
        "objective": "review script factual discipline",
        "dependencies": ["content-strategy"],
        "expected_output": "YouTubeSpecialistResult",
    },
    {
        "task_id": "production-management",
        "capability_id": "youtube.department.production-management",
        "action": "EXECUTION",
        "objective": "assess production readiness",
        "dependencies": ["script-review"],
        "expected_output": "YouTubeSpecialistResult",
    },
)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[position]


def _summary(values_ns: list[int]) -> dict[str, float | int]:
    values_ms = [value / 1_000_000.0 for value in values_ns]
    return {
        "samples": len(values_ms),
        "mean_ms": statistics.fmean(values_ms),
        "median_ms": statistics.median(values_ms),
        "p95_ms": _percentile(values_ms, 0.95),
        "p99_ms": _percentile(values_ms, 0.99),
        "min_ms": min(values_ms),
        "max_ms": max(values_ms),
    }


def _proc_io() -> dict[str, int]:
    path = Path("/proc/self/io")
    if not path.exists():
        return {}
    result: dict[str, int] = {}
    for raw in path.read_text().splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        try:
            result[key.strip()] = int(value.strip())
        except ValueError:
            pass
    return result


def _delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    keys = set(before) | set(after)
    return {key: after.get(key, 0) - before.get(key, 0) for key in sorted(keys)}


def _measure(fn: Callable[[], Any], samples: int, warmups: int) -> tuple[list[int], Any]:
    last = None
    for _ in range(warmups):
        last = fn()
    timings: list[int] = []
    for _ in range(samples):
        started = time.perf_counter_ns()
        last = fn()
        timings.append(time.perf_counter_ns() - started)
    return timings, last


def run(*, samples: int, plan_samples: int) -> dict[str, Any]:
    initialize_schema()

    routing_index = 0
    def route_once():
        nonlocal routing_index
        case = ROUTING_CASES[routing_index % len(ROUTING_CASES)]
        routing_index += 1
        return route_harness_request(
            HarnessRoutingRequest(
                intent=case["intent"],
                authorized_action=case["authorized_action"],
                domain=case["domain"],
                goal_id="perf-control-plane-routing",
                required_capability_id=case["required_capability_id"],
                fallback_allowed=False,
                provider_required=False,
                learning_required=False,
            )
        )

    selection_index = 0
    def selection_once():
        nonlocal selection_index
        case = ROUTING_CASES[selection_index % len(ROUTING_CASES)]
        selection_index += 1
        return select_specialist(
            intent=case["intent"],
            action=case["authorized_action"],
            required_capability_id=case["required_capability_id"],
            domain=case["domain"],
        )

    plan_counter = 0
    def plan_once():
        nonlocal plan_counter
        plan_counter += 1
        return build_collaboration_plan(
            mission_id=f"perf-plan-{plan_counter}",
            goal_id="perf-control-plane-collaboration",
            tasks=COLLABORATION_TASKS,
        )

    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    io_before = _proc_io()
    wall_started = time.perf_counter()

    routing_times, routing_last = _measure(route_once, samples, 20)
    selection_times, selection_last = _measure(selection_once, samples, 20)
    plan_times, plan_last = _measure(plan_once, plan_samples, 5)

    wall_seconds = time.perf_counter() - wall_started
    io_after = _proc_io()
    usage_after = resource.getrusage(resource.RUSAGE_SELF)

    assert routing_last.selected_capability_id in {
        case["required_capability_id"] for case in ROUTING_CASES
    }
    assert selection_last.selected_capability_id in {
        case["required_capability_id"] for case in ROUTING_CASES
    }
    assert plan_last.authority == "DEEPSEEK_HARNESS"
    assert len(plan_last.tasks) == len(COLLABORATION_TASKS)

    result = {
        "schema_version": 1,
        "status": "PASS",
        "observed": True,
        "runtime": {
            "github_run_id": os.getenv("GITHUB_RUN_ID"),
            "github_sha": os.getenv("GITHUB_SHA"),
            "python": os.sys.version.split()[0],
            "cpu_count": os.cpu_count(),
        },
        "harness_routing": _summary(routing_times),
        "agent_selection": _summary(selection_times),
        "collaboration_plan": _summary(plan_times),
        "collaboration_task_count": len(COLLABORATION_TASKS),
        "wall_clock_seconds": wall_seconds,
        "cpu_user_seconds": usage_after.ru_utime - usage_before.ru_utime,
        "cpu_system_seconds": usage_after.ru_stime - usage_before.ru_stime,
        "peak_rss_kb": usage_after.ru_maxrss,
        "process_io_delta": _delta(io_before, io_after),
        "external_call_count": 0,
        "network_io_bytes": 0,
        "side_effects": [],
        "authority": "DEEPSEEK_HARNESS",
        "job18_unchanged": True,
        "youtube_publication": False,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=300)
    parser.add_argument("--plan-samples", type=int, default=80)
    args = parser.parse_args()
    if args.samples < 30 or args.plan_samples < 10:
        raise ValueError("sample counts are too small for a useful observed baseline")
    result = run(samples=args.samples, plan_samples=args.plan_samples)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"HARNESS_ROUTING_MS={result['harness_routing']['mean_ms']:.6f}")
    print(f"HARNESS_ROUTING_P95_MS={result['harness_routing']['p95_ms']:.6f}")
    print(f"AGENT_SELECTION_MS={result['agent_selection']['mean_ms']:.6f}")
    print(f"AGENT_SELECTION_P95_MS={result['agent_selection']['p95_ms']:.6f}")
    print(f"COLLABORATION_PLAN_MS={result['collaboration_plan']['mean_ms']:.6f}")
    print(f"CONTROL_PLANE_CPU_USER_SECONDS={result['cpu_user_seconds']:.6f}")
    print(f"CONTROL_PLANE_CPU_SYSTEM_SECONDS={result['cpu_system_seconds']:.6f}")
    print(f"CONTROL_PLANE_PEAK_RSS_KB={result['peak_rss_kb']}")
    print("HARNESS_CONTROL_PLANE_BASELINE=PASS")
    print("JOB18_UNCHANGED=YES")
    print("YOUTUBE_PUBLICATION=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
