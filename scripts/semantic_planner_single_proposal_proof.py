from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import threading
import time
from typing import Any

import psutil

from app.database.schema import initialize_schema
from app.services.bounded_memory_context_service import build_bounded_memory_context
from app.services.continuous_operation_policy_service import load_continuous_operation_policy
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_adaptive_planning_service import build_semantic_planning_context
from app.services.harness_collaboration_service import (
    build_goal_envelope,
    plan_mission_from_human_goal,
)
from app.services.local_openweight_ai_provider import (
    LOCAL_OPENWEIGHT_MODEL_ID,
    LOCAL_OPENWEIGHT_PROVIDER_ID,
    _semantic_context_window,
    semantic_planner_num_predict,
)
from app.services.provider_health_service import semantic_provider_health
from app.services.semantic_mission_planner_service import (
    SemanticPlannerProviderFailure,
    build_semantic_planner_prompt,
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


def _resource_bounds(resources: dict[str, Any]) -> dict[str, int]:
    return {
        key: int(resources[key])
        for key in (
            "max_tasks_per_mission",
            "max_retries_per_task",
            "max_reviewer_loops",
            "max_parallelism",
            "mission_timeout_seconds",
            "bounded_memory_bytes",
        )
    }


def _memories_used(retrieval: dict[str, Any]) -> int:
    bounded = dict(retrieval.get("bounded_memory_sections") or {})
    return (
        int(retrieval.get("relevant_failure_memories") or 0)
        + int(retrieval.get("recent_execution_history") or 0)
        + int(retrieval.get("human_feedback_decisions") or 0)
        + sum(int(value or 0) for value in bounded.values())
    )


def _persist(output: Path, report: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _preflight(goal) -> tuple[dict[str, Any], str, dict[str, Any]]:
    policy = load_continuous_operation_policy()
    resources = dict(policy.resource_governance)
    memory = build_bounded_memory_context(
        goal_id=goal.goal_id,
        domain="system-improvement",
        task_class=goal.mission_class.casefold().replace("_", "-"),
        artifact_ref=None,
        intent=goal.human_goal,
        max_bytes=int(resources["bounded_memory_bytes"]),
    ).to_dict()
    context = build_semantic_planning_context(
        goal=goal.to_dict(),
        bounded_memory_context=memory,
        resource_bounds=_resource_bounds(resources),
        provider_health=semantic_provider_health(),
        artifact_ref=None,
    )
    prompt = build_semantic_planner_prompt(context)
    selected_num_predict = semantic_planner_num_predict()
    num_ctx, prompt_token_estimate = _semantic_context_window(
        prompt,
        num_predict=selected_num_predict,
    )
    retrieval = dict(context.get("context_retrieval_evidence") or {})
    return context, prompt, {
        "prompt_bytes": len(prompt.encode("utf-8")),
        "prompt_token_estimate": prompt_token_estimate,
        "context_capabilities": len(context.get("registry_summary") or ()),
        "registry_total_executable": retrieval.get("registry_total_executable"),
        "memories_used": _memories_used(retrieval),
        "num_ctx": num_ctx,
        "num_predict": selected_num_predict,
        "structured_json_mode": True,
        "structured_json_schema_mode": str(
            os.getenv("BR_LOCAL_SEMANTIC_SCHEMA") or ""
        ).strip() in {"1", "true", "TRUE", "yes", "YES"},
        "context_retrieval": retrieval,
    }


def _print_report(report: dict[str, Any]) -> None:
    print("COLD_START_PROPOSAL=YES")
    print("STATUS=" + str(report.get("status")))
    print("FAILURE_STAGE=" + str(report.get("failure_stage")))
    print("ERROR_CODE=" + str(report.get("error_code")))
    print("PROVIDER=" + str(report.get("provider")))
    print(
        "PROVIDER_LIVE_INFERENCE="
        + ("PASS" if report.get("provider_live_inference") else "FAIL")
    )
    print("PROMPT_BYTES=" + str(report.get("prompt_bytes")))
    print("PROMPT_TOKENS=" + str(report.get("prompt_tokens")))
    print("PROMPT_TOKEN_ESTIMATE=" + str(report.get("prompt_token_estimate")))
    print("CONTEXT_CAPABILITIES=" + str(report.get("context_capabilities")))
    print("MEMORIES_USED=" + str(report.get("memories_used")))
    print("NUM_CTX=" + str(report.get("num_ctx")))
    print("NUM_PREDICT=" + str(report.get("num_predict")))
    print("FINISH_REASON=" + str(report.get("finish_reason")))
    print(
        "OUTPUT_TRUNCATED="
        + ("YES" if report.get("output_truncated") else "NO")
    )
    print(
        "INFERENCE_LATENCY_SECONDS="
        + f"{float(report.get('inference_latency_seconds') or 0.0):.3f}"
    )
    print("PROMPT_EVAL_SECONDS=" + str(report.get("prompt_eval_seconds")))
    print(
        "PROMPT_EVAL_TOKENS_PER_SECOND="
        + str(report.get("prompt_eval_tokens_per_second"))
    )
    print("GENERATION_SECONDS=" + str(report.get("generation_seconds")))
    print(
        "GENERATION_TOKENS_PER_SECOND="
        + str(report.get("generation_tokens_per_second"))
    )
    print("GENERATED_TOKENS=" + str(report.get("generated_tokens")))
    print("PEAK_RSS_MB=" + f"{float(report.get('peak_rss_mb') or 0.0):.3f}")
    print("PEAK_CPU=" + f"{float(report.get('peak_cpu') or 0.0):.3f}")
    print(
        "STRICT_JSON_VALID="
        + ("PASS" if report.get("strict_json_valid") else "FAIL")
    )
    print(
        "MISSION_PLAN_SCHEMA_VALID="
        + ("PASS" if report.get("mission_plan_schema_valid") else "FAIL")
    )
    print(
        "SEMANTIC_PLAN_JSON_VALID="
        + ("PASS" if report.get("semantic_plan_json_valid") else "FAIL")
    )
    print(
        "REGISTRY_VALIDATION="
        + ("PASS" if report.get("registry_validation") else "FAIL")
    )
    print(
        "SINGLE_PROPOSAL_PERFORMANCE_PROOF="
        + str(report.get("SINGLE_PROPOSAL_PERFORMANCE_PROOF"))
    )


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
    _context, _prompt, preflight = _preflight(goal)

    report: dict[str, Any] = {
        "status": "RUNNING",
        "failure_stage": None,
        "error_code": None,
        "human_goal": GOAL,
        "provider_inference_injected": False,
        "planning_mode": "SEMANTIC_ADAPTIVE",
        "provider": LOCAL_OPENWEIGHT_PROVIDER_ID,
        "model": LOCAL_OPENWEIGHT_MODEL_ID,
        "provider_live_inference": False,
        **preflight,
        "prompt_tokens": None,
        "inference_latency_seconds": None,
        "prompt_eval_seconds": None,
        "prompt_eval_tokens_per_second": None,
        "generation_seconds": None,
        "generation_tokens_per_second": None,
        "generated_tokens": None,
        "load_duration_seconds": None,
        "total_duration_seconds": None,
        "time_to_first_token_seconds": None,
        "finish_reason": None,
        "output_truncated": None,
        "strict_json_valid": False,
        "mission_plan_schema_valid": False,
        "peak_rss_mb": None,
        "peak_cpu": None,
        "average_host_cpu_percent": None,
        "semantic_plan_json_valid": False,
        "registry_validation": False,
        "registry_validation_errors": [],
        "provider_evidence": {},
        "performance": {},
        "usage": {},
        "bounded_latency_under_180_seconds": False,
        "SINGLE_PROPOSAL_PERFORMANCE_PROOF": "FAIL",
    }
    _persist(output, report)

    resources: dict[str, float] = {}
    stop = threading.Event()
    sampler = threading.Thread(
        target=_sample_resources,
        args=(stop, resources),
        daemon=True,
    )
    sampler.start()
    started = time.perf_counter()
    plan = None
    provider: dict[str, Any] = {}
    performance: dict[str, Any] = {}
    usage: dict[str, Any] = {}
    try:
        plan = plan_mission_from_human_goal(goal)
    except SemanticPlannerProviderFailure as exc:
        provider = dict(exc.evidence or {})
        performance = dict(provider.get("performance") or {})
        report.update({
            "status": "FAIL",
            "failure_stage": "provider_inference",
            "error_code": exc.code,
            "provider_evidence": provider,
            "performance": performance,
            "provider": provider.get("provider") or report["provider"],
            "model": provider.get("model") or report["model"],
            "inference_latency_seconds": (
                provider.get("latency_seconds")
                or performance.get("latency_seconds")
            ),
        })
    except Exception as exc:
        report.update({
            "status": "FAIL",
            "failure_stage": "planning",
            "error_code": type(exc).__name__,
            "error": str(exc)[:1200],
        })
    finally:
        wall = time.perf_counter() - started
        stop.set()
        sampler.join(timeout=3)
        report["wall_latency_seconds"] = wall
        report["peak_rss_mb"] = resources.get("peak_rss_mb")
        report["peak_cpu"] = resources.get("peak_ollama_cpu_percent")
        report["average_host_cpu_percent"] = resources.get(
            "average_host_cpu_percent"
        )

    if plan is not None:
        registry_ok, registry_errors = _registry_valid(plan)
        evidence = dict(plan.planning_evidence or {})
        provider = dict(evidence.get("provider_evidence") or {})
        performance = dict(provider.get("performance") or {})
        usage = dict(provider.get("usage") or {})
        retrieval = dict(evidence.get("context_retrieval") or {})
        latency = float(
            provider.get("latency_seconds")
            or performance.get("latency_seconds")
            or report.get("wall_latency_seconds")
            or 0.0
        )
        provider_ok = (
            provider.get("provider") == LOCAL_OPENWEIGHT_PROVIDER_ID
            and provider.get("status") == "EXECUTED"
        )
        schema_valid = bool(plan.semantic_plan_proposal)
        strict_json_valid = bool(provider.get("strict_json_valid"))
        finish_reason = str(
            provider.get("finish_reason")
            or performance.get("finish_reason")
            or ""
        ) or None
        output_truncated = bool(performance.get("output_truncated"))
        bounded_latency = latency < 180.0
        pass_all = all((
            plan.planning_mode == "SEMANTIC_ADAPTIVE",
            provider_ok,
            int(performance.get("prompt_bytes") or report["prompt_bytes"]) > 0,
            isinstance(usage.get("prompt_tokens"), int)
            and int(usage.get("prompt_tokens") or 0) > 0,
            int(retrieval.get("registry_candidates") or 0) <= 10,
            strict_json_valid,
            schema_valid,
            registry_ok,
            finish_reason == "stop",
            not output_truncated,
            bounded_latency,
        ))
        report.update({
            "status": "PASS" if pass_all else "FAIL",
            "failure_stage": None if pass_all else "post_inference_validation",
            "error_code": None if pass_all else "single_proposal_gate_failed",
            "mission_id": plan.mission_id,
            "plan_id": plan.plan_id,
            "provider": provider.get("provider"),
            "model": provider.get("model"),
            "provider_live_inference": provider_ok,
            "prompt_bytes": int(
                performance.get("prompt_bytes") or report["prompt_bytes"]
            ),
            "prompt_tokens": usage.get("prompt_tokens"),
            "prompt_token_estimate": performance.get(
                "prompt_token_estimate",
                report["prompt_token_estimate"],
            ),
            "context_capabilities": retrieval.get(
                "registry_candidates",
                report["context_capabilities"],
            ),
            "registry_total_executable": retrieval.get(
                "registry_total_executable",
                report["registry_total_executable"],
            ),
            "memories_used": _memories_used(retrieval),
            "inference_latency_seconds": latency,
            "num_ctx": performance.get("num_ctx", report["num_ctx"]),
            "num_predict": performance.get(
                "requested_output_tokens",
                report["num_predict"],
            ),
            "structured_json_mode": performance.get(
                "structured_json_mode",
                report["structured_json_mode"],
            ),
            "structured_json_schema_mode": performance.get(
                "structured_json_schema_mode",
                report["structured_json_schema_mode"],
            ),
            "finish_reason": finish_reason,
            "output_truncated": output_truncated,
            "strict_json_valid": strict_json_valid,
            "mission_plan_schema_valid": schema_valid,
            "semantic_plan_json_valid": schema_valid,
            "registry_validation": registry_ok,
            "registry_validation_errors": registry_errors,
            "task_ids": [
                task.task_id for task in plan.collaboration_plan.tasks
            ],
            "capability_ids": [
                task.capability_id for task in plan.collaboration_plan.tasks
            ],
            "context_retrieval": retrieval,
            "provider_evidence": provider,
            "performance": performance,
            "usage": usage,
            "bounded_latency_under_180_seconds": bounded_latency,
            "SINGLE_PROPOSAL_PERFORMANCE_PROOF": (
                "PASS" if pass_all else "FAIL"
            ),
        })

    performance = dict(report.get("performance") or {})
    report["prompt_eval_seconds"] = performance.get(
        "prompt_eval_duration_seconds"
    )
    report["prompt_eval_tokens_per_second"] = performance.get(
        "prompt_eval_tokens_per_second"
    )
    report["generation_seconds"] = performance.get("eval_duration_seconds")
    report["generation_tokens_per_second"] = performance.get(
        "generation_tokens_per_second"
    )
    report["generated_tokens"] = performance.get("generation_tokens")
    report["load_duration_seconds"] = performance.get(
        "ollama_load_duration_seconds"
    )
    report["total_duration_seconds"] = performance.get(
        "ollama_total_duration_seconds"
    )
    report["time_to_first_token_seconds"] = performance.get(
        "time_to_first_token_seconds"
    )
    if report.get("inference_latency_seconds") is None:
        report["inference_latency_seconds"] = report.get(
            "wall_latency_seconds"
        )

    _persist(output, report)
    _print_report(report)
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
