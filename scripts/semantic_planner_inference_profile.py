from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any

import psutil

from app.database.schema import initialize_schema
from app.services.bounded_memory_context_service import build_bounded_memory_context
from app.services.continuous_operation_policy_service import load_continuous_operation_policy
from app.services.harness_adaptive_planning_service import (
    build_semantic_planning_context,
    proposal_registry_errors,
)
from app.services.harness_collaboration_service import build_goal_envelope
from app.services.provider_health_service import semantic_provider_health
from app.services.semantic_mission_planner_service import (
    MissionPlanProposal,
    _json_object,
    build_semantic_planner_prompt,
)


GOAL = "Isso está uma carroça, descobre sozinho o que está acontecendo."
MODEL = "qwen3:4b-instruct"
CURRENT_NUM_CTX = 32768
CURRENT_NUM_PREDICT = 1800
CURRENT_TIMEOUT_SECONDS = 300


def _json_bytes(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    )


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


def _semantic_context() -> dict[str, Any]:
    initialize_schema()
    goal = build_goal_envelope(
        human_goal=GOAL,
        project="BR-no-GTA",
        goal_id="semantic-inference-profile-current",
        subject="desempenho geral do sistema",
        source_surface="semantic-inference-profile",
        canonical_state={
            "active_project": "BR-no-GTA",
            "execution_status": "investigation-requested",
        },
        conversation_state={
            "active_stage": "execution",
            "prior_observation": "latência percebida aumentou sem causa confirmada",
        },
    )
    policy = load_continuous_operation_policy()
    resources = dict(policy.resource_governance)
    memory = build_bounded_memory_context(
        goal_id=goal.goal_id,
        domain="system-improvement",
        task_class="system-improvement",
        artifact_ref=None,
        intent=goal.human_goal,
        max_bytes=int(resources["bounded_memory_bytes"]),
    ).to_dict()
    return build_semantic_planning_context(
        goal=goal.to_dict(),
        bounded_memory_context=memory,
        resource_bounds=_resource_bounds(resources),
        provider_health=semantic_provider_health(),
        artifact_ref=None,
    )


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


def _run_streaming_profile(prompt: str) -> dict[str, Any]:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "options": {
            "temperature": 0.1,
            "num_ctx": CURRENT_NUM_CTX,
            "num_predict": CURRENT_NUM_PREDICT,
        },
    }
    payload_path = Path("/tmp/semantic-profile-payload.json")
    payload_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    cmd = [
        "curl",
        "--no-buffer",
        "--silent",
        "--show-error",
        "--max-time",
        str(CURRENT_TIMEOUT_SECONDS),
        "-H",
        "Content-Type: application/json",
        "--data-binary",
        "@" + str(payload_path),
        "http://127.0.0.1:11434/api/chat",
    ]
    stop = threading.Event()
    resources: dict[str, float] = {}
    sampler = threading.Thread(
        target=_sample_resources,
        args=(stop, resources),
        daemon=True,
    )
    sampler.start()
    started = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    first_token_seconds: float | None = None
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    final: dict[str, Any] = {}
    event_count = 0
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.strip()
        if not line:
            continue
        event_count += 1
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message") if isinstance(event, dict) else None
        if isinstance(message, dict):
            content = str(message.get("content") or "")
            thinking = str(message.get("thinking") or "")
            if content:
                content_parts.append(content)
            if thinking:
                thinking_parts.append(thinking)
            if first_token_seconds is None and (content or thinking):
                first_token_seconds = time.perf_counter() - started
        if bool(event.get("done")):
            final = dict(event)
    stderr = ""
    if proc.stderr is not None:
        stderr = proc.stderr.read()
    return_code = proc.wait()
    latency = time.perf_counter() - started
    stop.set()
    sampler.join(timeout=3)

    prompt_eval_count = final.get("prompt_eval_count")
    eval_count = final.get("eval_count")
    prompt_eval_duration_ns = final.get("prompt_eval_duration")
    eval_duration_ns = final.get("eval_duration")

    def rate(count: Any, duration_ns: Any) -> float | None:
        if not isinstance(count, int) or not isinstance(duration_ns, int) or duration_ns <= 0:
            return None
        return float(count) / (float(duration_ns) / 1_000_000_000.0)

    text = "".join(content_parts).strip()
    json_valid = False
    registry_valid = False
    parse_error: str | None = None
    validation_errors: list[str] = []
    if text:
        try:
            mapping = _json_object(text)
            proposal = MissionPlanProposal.from_mapping(mapping, max_tasks=8)
            json_valid = True
            validation_errors = list(proposal_registry_errors(proposal))
            registry_valid = not validation_errors
        except Exception as exc:
            parse_error = f"{type(exc).__name__}:{exc}"[:1200]

    return {
        "return_code": return_code,
        "timed_out": return_code == 28,
        "stderr": stderr[-1200:],
        "event_count": event_count,
        "inference_latency_seconds": latency,
        "time_to_first_token_seconds": first_token_seconds,
        "response_content_bytes": len(text.encode("utf-8")),
        "thinking_bytes": len("".join(thinking_parts).encode("utf-8")),
        "prompt_eval_count": prompt_eval_count,
        "eval_count": eval_count,
        "prompt_eval_duration_seconds": (
            float(prompt_eval_duration_ns) / 1_000_000_000.0
            if isinstance(prompt_eval_duration_ns, int)
            else None
        ),
        "eval_duration_seconds": (
            float(eval_duration_ns) / 1_000_000_000.0
            if isinstance(eval_duration_ns, int)
            else None
        ),
        "prompt_eval_tokens_per_second": rate(
            prompt_eval_count, prompt_eval_duration_ns
        ),
        "generation_tokens_per_second": rate(eval_count, eval_duration_ns),
        "semantic_plan_json_valid": json_valid,
        "registry_validation": registry_valid,
        "validation_errors": validation_errors,
        "parse_error": parse_error,
        **resources,
    }


def run(output: Path) -> dict[str, Any]:
    context = _semantic_context()
    prompt = build_semantic_planner_prompt(context)
    block_keys = (
        "registry_summary",
        "competence_evidence",
        "bounded_memory_context",
        "recent_execution_history",
        "relevant_failure_memories",
        "human_feedback_decisions",
        "canonical_state",
        "conversation_state",
        "provider_health",
        "known_bad_paths",
        "resource_bounds",
    )
    block_bytes = {key: _json_bytes(context.get(key)) for key in block_keys}
    profile = _run_streaming_profile(prompt)
    report = {
        "profile_kind": "CURRENT_UNOPTIMIZED_SEMANTIC_INFERENCE",
        "human_goal": GOAL,
        "model": MODEL,
        "num_ctx": CURRENT_NUM_CTX,
        "num_predict": CURRENT_NUM_PREDICT,
        "request_timeout_seconds": CURRENT_TIMEOUT_SECONDS,
        "prompt_bytes": len(prompt.encode("utf-8")),
        "prompt_token_estimate_chars_div_4": (
            len(prompt.encode("utf-8")) + 3
        ) // 4,
        "context_capabilities": len(context.get("registry_summary") or ()),
        "competence_rows": len(context.get("competence_evidence") or ()),
        "memories_used": len(context.get("relevant_failure_memories") or ())
        + len(context.get("human_feedback_decisions") or ())
        + len(context.get("recent_execution_history") or ()),
        "context_block_bytes": block_bytes,
        "inference": profile,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"PROMPT_BYTES={report['prompt_bytes']}")
    print(f"PROMPT_TOKEN_ESTIMATE={report['prompt_token_estimate_chars_div_4']}")
    print(f"CONTEXT_CAPABILITIES={report['context_capabilities']}")
    print(f"COMPETENCE_ROWS={report['competence_rows']}")
    print(f"MEMORIES_USED={report['memories_used']}")
    print(f"INFERENCE_LATENCY_SECONDS={profile['inference_latency_seconds']:.3f}")
    print("PROMPT_TOKENS=" + str(profile.get("prompt_eval_count") or "UNAVAILABLE"))
    print("TIME_TO_FIRST_TOKEN_SECONDS=" + str(profile.get("time_to_first_token_seconds")))
    print("PROMPT_EVAL_TOKENS_PER_SECOND=" + str(profile.get("prompt_eval_tokens_per_second")))
    print("GENERATION_TOKENS_PER_SECOND=" + str(profile.get("generation_tokens_per_second")))
    print(f"PEAK_RSS_MB={profile.get('peak_rss_mb', 0.0):.3f}")
    print(f"PEAK_OLLAMA_CPU_PERCENT={profile.get('peak_ollama_cpu_percent', 0.0):.3f}")
    print("SEMANTIC_PLAN_JSON_VALID=" + ("PASS" if profile["semantic_plan_json_valid"] else "FAIL"))
    print("REGISTRY_VALIDATION=" + ("PASS" if profile["registry_validation"] else "FAIL"))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/semantic-inference-profile/current-profile.json",
    )
    args = parser.parse_args()
    run(Path(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
