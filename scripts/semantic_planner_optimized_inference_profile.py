from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any

from app.services.harness_adaptive_planning_service import proposal_registry_errors
from app.services.local_openweight_ai_provider import _semantic_context_window
from app.services.semantic_mission_planner_service import (
    MissionPlanProposal,
    build_semantic_planner_prompt,
    expand_compact_mission_plan_mapping,
    mission_plan_json_schema,
    semantic_prompt_component_bytes,
)
from scripts.semantic_planner_inference_profile import (
    _sample_resources,
    _semantic_context,
)


MODEL = "qwen3:4b-instruct"
LOCAL_PROVIDER_ROLE = "diagnostic_profile"
HISTORICAL_TRUNCATED_BUDGETS = (256, 384, 512)
SINGLE_OUTPUT_TOKEN_BUDGET = 1024
ATTEMPT_TIMEOUT_SECONDS = 90


def _rate(count: Any, duration_ns: Any) -> float | None:
    if not isinstance(count, int) or not isinstance(duration_ns, int) or duration_ns <= 0:
        return None
    return float(count) / (float(duration_ns) / 1_000_000_000.0)


def _ns_to_ms(value: Any) -> float | None:
    if not isinstance(value, int):
        return None
    return float(value) / 1_000_000.0


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_proposal(
    prompt: str,
    *,
    num_predict: int,
    num_ctx: int,
    cold_start: bool,
) -> dict[str, Any]:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "format": mission_plan_json_schema(max_tasks=8),
        "keep_alive": "10m",
        "options": {
            "temperature": 0.1,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }
    payload_path = Path("/tmp/semantic-diagnostic-schema.json")
    payload_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
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
    proc = subprocess.Popen(
        [
            "curl",
            "--no-buffer",
            "--silent",
            "--show-error",
            "--max-time",
            str(ATTEMPT_TIMEOUT_SECONDS),
            "-H",
            "Content-Type: application/json",
            "--data-binary",
            "@" + str(payload_path),
            "http://127.0.0.1:11434/api/chat",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    first_token_seconds = None
    content_parts: list[str] = []
    final: dict[str, Any] = {}
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message") if isinstance(event, dict) else None
        if isinstance(message, dict):
            content = str(message.get("content") or "")
            if content:
                content_parts.append(content)
                if first_token_seconds is None:
                    first_token_seconds = time.perf_counter() - started
        if bool(event.get("done")):
            final = dict(event)

    stderr = proc.stderr.read() if proc.stderr is not None else ""
    return_code = proc.wait()
    latency_seconds = time.perf_counter() - started
    stop.set()
    sampler.join(timeout=3)

    text = "".join(content_parts).strip()
    strict_json_valid = False
    schema_valid = False
    registry_valid = False
    validation_errors: list[str] = []
    parse_error = None
    task_count = None
    try:
        mapping = json.loads(text)
        strict_json_valid = isinstance(mapping, dict)
        if strict_json_valid:
            proposal = MissionPlanProposal.from_mapping(
                expand_compact_mission_plan_mapping(mapping),
                max_tasks=8,
            )
            schema_valid = True
            task_count = len(proposal.tasks)
            validation_errors = list(proposal_registry_errors(proposal))
            registry_valid = not validation_errors
    except Exception as exc:
        parse_error = f"{type(exc).__name__}:{exc}"[:1200]

    eval_count = final.get("eval_count")
    finish_reason = str(final.get("done_reason") or "")
    output_truncated = bool(
        finish_reason == "length"
        or (
            isinstance(eval_count, int)
            and eval_count >= num_predict
            and finish_reason != "stop"
        )
    )
    return {
        "cold_start": cold_start,
        "num_predict": num_predict,
        "num_ctx": num_ctx,
        "return_code": return_code,
        "timed_out": return_code == 28,
        "stderr": stderr[-1200:],
        "TTFT_MS": (
            round(first_token_seconds * 1000.0, 3)
            if first_token_seconds is not None
            else None
        ),
        "TOTAL_INFERENCE_MS": round(latency_seconds * 1000.0, 3),
        "MODEL_LOAD_MS": _ns_to_ms(final.get("load_duration")),
        "PROMPT_EVAL_MS": _ns_to_ms(final.get("prompt_eval_duration")),
        "GENERATION_MS": _ns_to_ms(final.get("eval_duration")),
        "prompt_eval_count": final.get("prompt_eval_count"),
        "prompt_eval_tokens_per_second": _rate(
            final.get("prompt_eval_count"),
            final.get("prompt_eval_duration"),
        ),
        "OUTPUT_TOKENS": eval_count,
        "generation_tokens_per_second": _rate(
            eval_count,
            final.get("eval_duration"),
        ),
        "FINISH_REASON": finish_reason,
        "output_truncated": output_truncated,
        "strict_json_valid": strict_json_valid,
        "mission_plan_schema_valid": schema_valid,
        "full_registry_validation": registry_valid,
        "validation_errors": validation_errors,
        "parse_error": parse_error,
        "task_count": task_count,
        "response_content_bytes": len(text.encode("utf-8")),
        **resources,
    }


def _attempt_valid(attempt: dict[str, Any]) -> bool:
    return all(
        (
            attempt.get("return_code") == 0,
            attempt.get("FINISH_REASON") == "stop",
            not attempt.get("output_truncated"),
            attempt.get("strict_json_valid"),
            attempt.get("mission_plan_schema_valid"),
            attempt.get("full_registry_validation"),
        )
    )


def _failure_class(attempt: dict[str, Any]) -> str | None:
    if attempt.get("timed_out"):
        return "DIAGNOSTIC_ATTEMPT_TIMEOUT"
    if attempt.get("output_truncated") or attempt.get("FINISH_REASON") == "length":
        return "OUTPUT_BUDGET_INSUFFICIENT"
    if not attempt.get("strict_json_valid"):
        return "STRUCTURED_OUTPUT_INVALID"
    if not attempt.get("mission_plan_schema_valid"):
        return "MISSION_PLAN_SCHEMA_INVALID"
    if not attempt.get("full_registry_validation"):
        return "REGISTRY_VALIDATION_FAILED"
    return None


def run(output: Path) -> dict[str, Any]:
    context = _semantic_context()
    prompt = build_semantic_planner_prompt(context)
    num_ctx, prompt_estimate = _semantic_context_window(
        prompt,
        num_predict=SINGLE_OUTPUT_TOKEN_BUDGET,
    )
    component_bytes = semantic_prompt_component_bytes(context)
    instruction_bytes = len(prompt.split("\n", 1)[0].encode("utf-8"))
    prompt_bound = prompt_estimate <= 2000

    report: dict[str, Any] = {
        "profile_kind": "SINGLE_BOUNDED_LOCAL_DIAGNOSTIC",
        "status": "RUNNING",
        "provider": "ollama_local",
        "model": MODEL,
        "LOCAL_PROVIDER_ROLE": LOCAL_PROVIDER_ROLE,
        "CRITICAL_PATH_PREREQUISITE": False,
        "fallback_eligibility": False,
        "historical_truncated_budgets": list(HISTORICAL_TRUNCATED_BUDGETS),
        "selected_num_predict": SINGLE_OUTPUT_TOKEN_BUDGET,
        "budget_derivation": (
            "single 1024-token attempt = 2x the largest historically observed "
            "truncated 512-token attempt; no serial token-budget search"
        ),
        "ATTEMPT_TIMEOUT_MS": ATTEMPT_TIMEOUT_SECONDS * 1000,
        "LOCAL_PROVIDER_BOOTSTRAP_MS": float(
            os.getenv("LOCAL_PROVIDER_BOOTSTRAP_MS") or 0.0
        ),
        "MODEL_PULL_MS": float(os.getenv("MODEL_PULL_MS") or 0.0),
        "prompt_bytes": len(prompt.encode("utf-8")),
        "prompt_token_estimate": prompt_estimate,
        "prompt_token_target_pass": prompt_bound,
        "prompt_component_bytes": {
            "instructions": instruction_bytes,
            **component_bytes,
        },
        "context_capabilities": len(context.get("registry_summary") or ()),
        "SERIAL_BUDGET_SEARCH_ATTEMPTS": 1,
        "semantic_attempts": [],
        "LOCAL_PROVIDER_PROFILE_RESULT": "RUNNING",
        "PROFILE_DIAGNOSTIC_CAPTURED": False,
    }
    _write_json(output, report)

    if not prompt_bound:
        report.update(
            {
                "status": "PASS",
                "LOCAL_PROVIDER_PROFILE_RESULT": "FAIL",
                "failure_class": "PROMPT_TOKEN_TARGET_EXCEEDED",
                "PROFILE_DIAGNOSTIC_CAPTURED": True,
            }
        )
        _write_json(output, report)
        return report

    cold = _run_proposal(
        prompt,
        num_predict=SINGLE_OUTPUT_TOKEN_BUDGET,
        num_ctx=num_ctx,
        cold_start=True,
    )
    report["semantic_attempts"].append(cold)
    report["COLD_PROMPT_EVAL_MS"] = cold.get("PROMPT_EVAL_MS")
    report["COLD_GENERATION_MS"] = cold.get("GENERATION_MS")
    report["MODEL_LOAD_MS"] = cold.get("MODEL_LOAD_MS")
    report["TTFT_MS"] = cold.get("TTFT_MS")
    report["TOTAL_INFERENCE_MS"] = cold.get("TOTAL_INFERENCE_MS")
    report["OUTPUT_TOKENS"] = cold.get("OUTPUT_TOKENS")
    report["FINISH_REASON"] = cold.get("FINISH_REASON")
    _write_json(output, report)

    warm = None
    if _attempt_valid(cold):
        warm = _run_proposal(
            prompt,
            num_predict=SINGLE_OUTPUT_TOKEN_BUDGET,
            num_ctx=num_ctx,
            cold_start=False,
        )
        report["semantic_attempts"].append(warm)
        report["WARM_PROMPT_EVAL_MS"] = warm.get("PROMPT_EVAL_MS")
        report["WARM_GENERATION_MS"] = warm.get("GENERATION_MS")
        report["WARM_TTFT_MS"] = warm.get("TTFT_MS")
        report["WARM_TOTAL_INFERENCE_MS"] = warm.get("TOTAL_INFERENCE_MS")

    profile_pass = _attempt_valid(cold) and bool(warm and _attempt_valid(warm))
    failure = None
    if not profile_pass:
        failure = _failure_class(cold)
        if failure is None and warm is not None:
            failure = _failure_class(warm)

    report.update(
        {
            "status": "PASS",
            "LOCAL_PROVIDER_PROFILE_RESULT": "PASS" if profile_pass else "FAIL",
            "failure_class": failure,
            "PROFILE_DIAGNOSTIC_CAPTURED": True,
        }
    )
    _write_json(output, report)

    print("LOCAL_PROVIDER_ROLE=" + LOCAL_PROVIDER_ROLE)
    print(
        "LOCAL_PROVIDER_PROFILE_RESULT="
        + str(report["LOCAL_PROVIDER_PROFILE_RESULT"])
    )
    print("PROFILE_DIAGNOSTIC_CAPTURED=PASS")
    print("SERIAL_BUDGET_SEARCH_ATTEMPTS=1")
    print("SELECTED_NUM_PREDICT=" + str(SINGLE_OUTPUT_TOKEN_BUDGET))
    print("LOCAL_PROVIDER_BOOTSTRAP_MS=" + str(report["LOCAL_PROVIDER_BOOTSTRAP_MS"]))
    print("MODEL_PULL_MS=" + str(report["MODEL_PULL_MS"]))
    print("MODEL_LOAD_MS=" + str(report.get("MODEL_LOAD_MS")))
    print("COLD_PROMPT_EVAL_MS=" + str(report.get("COLD_PROMPT_EVAL_MS")))
    print("COLD_GENERATION_MS=" + str(report.get("COLD_GENERATION_MS")))
    print("WARM_PROMPT_EVAL_MS=" + str(report.get("WARM_PROMPT_EVAL_MS")))
    print("WARM_GENERATION_MS=" + str(report.get("WARM_GENERATION_MS")))
    print("TTFT_MS=" + str(report.get("TTFT_MS")))
    print("TOTAL_INFERENCE_MS=" + str(report.get("TOTAL_INFERENCE_MS")))
    print("OUTPUT_TOKENS=" + str(report.get("OUTPUT_TOKENS")))
    print("FINISH_REASON=" + str(report.get("FINISH_REASON")))
    print("FAILURE_CLASS=" + str(report.get("failure_class")))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
