from __future__ import annotations

import argparse
import json
from pathlib import Path
import threading
import time
from typing import Any

import psutil

from app.database.schema import initialize_schema
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_collaboration_service import (
    build_goal_envelope,
    plan_mission_from_human_goal,
)


GOAL = "Isso está uma carroça, descobre sozinho o que está acontecendo."


def _ollama_processes() -> list[psutil.Process]:
    rows: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = str(proc.info.get("name") or "").casefold()
            cmd = " ".join(proc.info.get("cmdline") or ()).casefold()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if "ollama" in name or "ollama" in cmd:
            rows.append(proc)
    return rows


def _sample_resources(stop: threading.Event, out: dict[str, float]) -> None:
    known: dict[int, psutil.Process] = {}
    peak_rss = 0
    peak_cpu = 0.0
    host_cpu_sum = 0.0
    host_samples = 0
    while not stop.is_set():
        for proc in _ollama_processes():
            if proc.pid not in known:
                known[proc.pid] = proc
                try:
                    proc.cpu_percent(None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        rss = 0
        cpu = 0.0
        for pid, proc in list(known.items()):
            try:
                rss += int(proc.memory_info().rss)
                cpu += float(proc.cpu_percent(None))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                known.pop(pid, None)
        peak_rss = max(peak_rss, rss)
        peak_cpu = max(peak_cpu, cpu)
        host_cpu_sum += float(psutil.cpu_percent(None))
        host_samples += 1
        stop.wait(0.5)
    out["peak_rss_mb"] = peak_rss / (1024.0 * 1024.0)
    out["peak_ollama_cpu_percent"] = peak_cpu
    out["average_host_cpu_percent"] = (
        host_cpu_sum / host_samples if host_samples else 0.0
    )


def _registry_valid(plan) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for task in plan.collaboration_plan.tasks:
        record = GLOBAL_CAPABILITY_REGISTRY.get(task.capability_id)
        if record is None:
            errors.append(f"{task.task_id}:missing:{task.capability_id}")
            continue
        if not record.execution_enabled:
            errors.append(f"{task.task_id}:not-executable:{task.capability_id}")
        if task.action not in record.allowed_actions:
            errors.append(
                f"{task.task_id}:action:{task.action}:{task.capability_id}"
            )
        if task.selected_executor_binding != record.executor_binding:
            errors.append(
                f"{task.task_id}:executor-binding:{task.capability_id}"
            )
    return not errors, errors


def run(output: Path) -> dict[str, Any]:
    initialize_schema()
    goal = build_goal_envelope(
        human_goal=GOAL,
        project="BR-no-GTA",
        goal_id="semantic-single-proposal-performance-proof",
        subject="desempenho geral do sistema",
        source_surface="semantic-single-proposal-performance-proof",
        canonical_state={
            "active_project": "BR-no-GTA",
            "execution_status": "investigation-requested",
        },
        conversation_state={
            "active_stage": "execution",
            "prior_observation": "latência percebida aumentou sem causa confirmada",
        },
    )

    resources: dict[str, float] = {}
    stop = threading.Event()
    sampler = threading.Thread(
        target=_sample_resources,
        args=(stop, resources),
        daemon=True,
    )
    sampler.start()
    started = time.perf_counter()
    try:
        plan = plan_mission_from_human_goal(goal)
    finally:
        resources["wall_latency_seconds"] = time.perf_counter() - started
        stop.set()
        sampler.join(timeout=3)

    registry_ok, registry_errors = _registry_valid(plan)
    evidence = dict(plan.planning_evidence or {})
    provider = dict(evidence.get("provider_evidence") or {})
    performance = dict(provider.get("performance") or {})
    usage = dict(provider.get("usage") or {})
    retrieval = dict(evidence.get("context_retrieval") or {})
    bounded_sections = dict(retrieval.get("bounded_memory_sections") or {})
    memories_used = (
        int(retrieval.get("relevant_failure_memories") or 0)
        + int(retrieval.get("recent_execution_history") or 0)
        + int(retrieval.get("human_feedback_decisions") or 0)
        + sum(int(value or 0) for value in bounded_sections.values())
    )

    prompt_bytes = int(performance.get("prompt_bytes") or 0)
    prompt_tokens = usage.get("prompt_tokens")
    latency = float(
        provider.get("latency_seconds")
        or performance.get("latency_seconds")
        or resources.get("wall_latency_seconds")
        or 0.0
    )
    json_valid = bool(plan.semantic_plan_proposal)
    provider_ok = (
        provider.get("provider") == "ollama_local"
        and provider.get("status") == "EXECUTED"
    )
    bounded_latency = latency < 180.0
    pass_all = all((
        plan.planning_mode == "SEMANTIC_ADAPTIVE",
        provider_ok,
        prompt_bytes > 0,
        isinstance(prompt_tokens, int) and prompt_tokens > 0,
        int(retrieval.get("registry_candidates") or 0) <= 18,
        json_valid,
        registry_ok,
        bounded_latency,
    ))

    report = {
        "human_goal": GOAL,
        "provider_inference_injected": False,
        "planning_mode": plan.planning_mode,
        "mission_id": plan.mission_id,
        "plan_id": plan.plan_id,
        "provider": provider.get("provider"),
        "model": provider.get("model"),
        "prompt_bytes": prompt_bytes,
        "prompt_tokens": prompt_tokens,
        "prompt_token_estimate": performance.get("prompt_token_estimate"),
        "context_capabilities": retrieval.get("registry_candidates"),
        "registry_total_executable": retrieval.get("registry_total_executable"),
        "memories_used": memories_used,
        "inference_latency_seconds": latency,
        "prompt_eval_tokens_per_second": performance.get(
            "prompt_eval_tokens_per_second"
        ),
        "generation_tokens_per_second": performance.get(
            "generation_tokens_per_second"
        ),
        "peak_rss_mb": resources.get("peak_rss_mb"),
        "peak_ollama_cpu_percent": resources.get("peak_ollama_cpu_percent"),
        "average_host_cpu_percent": resources.get("average_host_cpu_percent"),
        "time_to_first_token_seconds": None,
        "time_to_first_token_available": False,
        "requested_output_tokens": performance.get("requested_output_tokens"),
        "num_ctx": performance.get("num_ctx"),
        "structured_json_mode": performance.get("structured_json_mode"),
        "semantic_plan_json_valid": json_valid,
        "registry_validation": registry_ok,
        "registry_validation_errors": registry_errors,
        "task_ids": [
            task.task_id for task in plan.collaboration_plan.tasks
        ],
        "capability_ids": [
            task.capability_id for task in plan.collaboration_plan.tasks
        ],
        "context_retrieval": retrieval,
        "performance": performance,
        "usage": usage,
        "bounded_latency_under_180_seconds": bounded_latency,
        "SINGLE_PROPOSAL_PERFORMANCE_PROOF": "PASS" if pass_all else "FAIL",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    print("PROMPT_BYTES=" + str(report["prompt_bytes"]))
    print("PROMPT_TOKENS=" + str(report["prompt_tokens"]))
    print("CONTEXT_CAPABILITIES=" + str(report["context_capabilities"]))
    print("MEMORIES_USED=" + str(report["memories_used"]))
    print(
        "INFERENCE_LATENCY_SECONDS="
        + f"{report['inference_latency_seconds']:.3f}"
    )
    print(
        "PROMPT_EVAL_TOKENS_PER_SECOND="
        + str(report["prompt_eval_tokens_per_second"])
    )
    print(
        "GENERATION_TOKENS_PER_SECOND="
        + str(report["generation_tokens_per_second"])
    )
    print("PEAK_RSS_MB=" + f"{float(report['peak_rss_mb'] or 0.0):.3f}")
    print(
        "SEMANTIC_PLAN_JSON_VALID="
        + ("PASS" if report["semantic_plan_json_valid"] else "FAIL")
    )
    print(
        "REGISTRY_VALIDATION="
        + ("PASS" if report["registry_validation"] else "FAIL")
    )
    print(
        "SINGLE_PROPOSAL_PERFORMANCE_PROOF="
        + report["SINGLE_PROPOSAL_PERFORMANCE_PROOF"]
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/harness-intelligence/single-proposal-performance.json",
    )
    args = parser.parse_args()
    report = run(Path(args.output))
    return 0 if report["SINGLE_PROPOSAL_PERFORMANCE_PROOF"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
