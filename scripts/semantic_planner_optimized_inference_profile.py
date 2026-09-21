from __future__ import annotations

import argparse
import json
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
    mission_plan_json_schema,
)
from scripts.semantic_planner_inference_profile import (
    _json_bytes,
    _sample_resources,
    _semantic_context,
)


MODEL = "qwen3:4b-instruct"
BUDGETS = (256, 384, 512)
ATTEMPT_TIMEOUT_SECONDS = 180
WARMUP_TIMEOUT_SECONDS = 90
MAX_PROMPT_TOKEN_ESTIMATE = 2000


def _rate(count: Any, duration_ns: Any) -> float | None:
    if not isinstance(count, int) or not isinstance(duration_ns, int) or duration_ns <= 0:
        return None
    return float(count) / (float(duration_ns) / 1_000_000_000.0)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _curl_json(payload: dict[str, Any], *, timeout: int, path: Path) -> tuple[int, str, str]:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        [
            "curl",
            "--silent",
            "--show-error",
            "--max-time",
            str(timeout),
            "-H",
            "Content-Type: application/json",
            "--data-binary",
            "@" + str(path),
            "http://127.0.0.1:11434/api/chat",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _warm_model() -> dict[str, Any]:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": 'Return exactly {"warm":true}.'}
        ],
        "stream": False,
        "format": "json",
        "keep_alive": "10m",
        "options": {
            "temperature": 0.0,
            "num_ctx": 2048,
            "num_predict": 16,
        },
    }
    started = time.perf_counter()
    code, stdout, stderr = _curl_json(
        payload,
        timeout=WARMUP_TIMEOUT_SECONDS,
        path=Path("/tmp/semantic-warmup.json"),
    )
    elapsed = time.perf_counter() - started
    valid = False
    try:
        body = json.loads(stdout)
        message = body.get("message") if isinstance(body, dict) else None
        parsed = json.loads(str(message.get("content") or ""))
        valid = isinstance(parsed, dict) and parsed.get("warm") is True
    except Exception:
        valid = False
    return {
        "return_code": code,
        "latency_seconds": elapsed,
        "valid": valid,
        "stderr": stderr[-1200:],
    }


def _probe_schema_support() -> dict[str, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["ok"],
        "properties": {"ok": {"type": "boolean"}},
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": "Return an object with ok=true."}
        ],
        "stream": False,
        "format": schema,
        "keep_alive": "10m",
        "options": {
            "temperature": 0.0,
            "num_ctx": 2048,
            "num_predict": 24,
        },
    }
    started = time.perf_counter()
    code, stdout, stderr = _curl_json(
        payload,
        timeout=WARMUP_TIMEOUT_SECONDS,
        path=Path("/tmp/semantic-schema-probe.json"),
    )
    elapsed = time.perf_counter() - started
    supported = False
    error = None
    try:
        body = json.loads(stdout)
        message = body.get("message") if isinstance(body, dict) else None
        parsed = json.loads(str(message.get("content") or ""))
        supported = isinstance(parsed, dict) and parsed == {"ok": True}
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"[:800]
    return {
        "return_code": code,
        "latency_seconds": elapsed,
        "supported": supported,
        "stderr": stderr[-1200:],
        "error": error,
    }


def _prompt_components(prompt: str, context: dict[str, Any]) -> dict[str, Any]:
    output_marker = "\nOUTPUT_CONTRACT="
    context_marker = "\nCONTEXT="
    output_at = prompt.find(output_marker)
    context_at = prompt.find(context_marker)
    if output_at < 0 or context_at < 0 or context_at <= output_at:
        return {"prompt_total": len(prompt.encode("utf-8"))}
    instructions = prompt[:output_at]
    output_contract = prompt[output_at + len(output_marker):context_at]
    context_blob = prompt[context_at + len(context_marker):]
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
    return {
        "prompt_total": len(prompt.encode("utf-8")),
        "instructions": len(instructions.encode("utf-8")),
        "output_contract": len(output_contract.encode("utf-8")),
        "context_serialized": len(context_blob.encode("utf-8")),
        "context_blocks": {
            key: _json_bytes(context.get(key))
            for key in block_keys
        },
    }


def _run_streaming_attempt(
    prompt: str,
    *,
    num_predict: int,
    num_ctx: int,
    format_spec: str | dict[str, Any],
    attempt_index: int,
) -> dict[str, Any]:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "format": format_spec,
        "keep_alive": "10m",
        "options": {
            "temperature": 0.1,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }
    payload_path = Path(f"/tmp/semantic-budget-{num_predict}.json")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

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

    stderr = proc.stderr.read() if proc.stderr is not None else ""
    return_code = proc.wait()
    latency = time.perf_counter() - started
    stop.set()
    sampler.join(timeout=3)

    text = "".join(content_parts).strip()
    strict_json_valid = False
    schema_valid = False
    registry_valid = False
    validation_errors: list[str] = []
    parse_error = None
    task_count = None
    if text:
        try:
            mapping = json.loads(text)
            strict_json_valid = isinstance(mapping, dict)
            if strict_json_valid:
                proposal = MissionPlanProposal.from_mapping(mapping, max_tasks=8)
                schema_valid = True
                task_count = len(proposal.tasks)
                validation_errors = list(proposal_registry_errors(proposal))
                registry_valid = not validation_errors
        except Exception as exc:
            parse_error = f"{type(exc).__name__}:{exc}"[:1200]

    prompt_eval_count = final.get("prompt_eval_count")
    eval_count = final.get("eval_count")
    prompt_eval_duration = final.get("prompt_eval_duration")
    eval_duration = final.get("eval_duration")
    total_duration = final.get("total_duration")
    load_duration = final.get("load_duration")
    finish_reason = str(final.get("done_reason") or "") or None
    output_truncated = bool(
        finish_reason == "length"
        or (
            isinstance(eval_count, int)
            and eval_count >= num_predict
            and finish_reason != "stop"
        )
    )

    return {
        "attempt_index": attempt_index,
        "prompt_cache_expected": attempt_index > 0,
        "latency_role": (
            "FIRST_REAL_PROMPT_AFTER_WARMUP"
            if attempt_index == 0
            else "BUDGET_SEARCH_WITH_PROMPT_CACHE"
        ),
        "num_predict": num_predict,
        "num_ctx": num_ctx,
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
        "finish_reason": finish_reason,
        "output_truncated": output_truncated,
        "prompt_eval_duration_seconds": (
            float(prompt_eval_duration) / 1_000_000_000.0
            if isinstance(prompt_eval_duration, int) else None
        ),
        "eval_duration_seconds": (
            float(eval_duration) / 1_000_000_000.0
            if isinstance(eval_duration, int) else None
        ),
        "total_duration_seconds": (
            float(total_duration) / 1_000_000_000.0
            if isinstance(total_duration, int) else None
        ),
        "load_duration_seconds": (
            float(load_duration) / 1_000_000_000.0
            if isinstance(load_duration, int) else None
        ),
        "prompt_eval_tokens_per_second": _rate(
            prompt_eval_count, prompt_eval_duration
        ),
        "generation_tokens_per_second": _rate(eval_count, eval_duration),
        "strict_json_valid": strict_json_valid,
        "mission_plan_schema_valid": schema_valid,
        "full_registry_validation": registry_valid,
        "validation_errors": validation_errors,
        "parse_error": parse_error,
        "task_count": task_count,
        "valid_sufficient_plan": bool(
            return_code == 0
            and not output_truncated
            and finish_reason == "stop"
            and strict_json_valid
            and schema_valid
            and registry_valid
            and isinstance(task_count, int)
            and task_count > 0
        ),
        **resources,
    }


def run(output: Path) -> dict[str, Any]:
    context = _semantic_context()
    prompt = build_semantic_planner_prompt(context)
    _, prompt_estimate = _semantic_context_window(prompt, num_predict=256)
    retrieval = dict(context.get("context_retrieval_evidence") or {})
    report: dict[str, Any] = {
        "profile_kind": "COMPACT_SCHEMA_BOUNDED_OUTPUT_SEARCH",
        "status": "RUNNING",
        "provider": "ollama_local",
        "model": MODEL,
        "prompt_bytes": len(prompt.encode("utf-8")),
        "prompt_token_estimate": prompt_estimate,
        "input_budget_max_tokens": MAX_PROMPT_TOKEN_ESTIMATE,
        "input_budget_pass": prompt_estimate <= MAX_PROMPT_TOKEN_ESTIMATE,
        "context_capabilities": len(context.get("registry_summary") or ()),
        "context_retrieval": retrieval,
        "prompt_component_bytes": _prompt_components(prompt, context),
        "warmup": {},
        "json_schema_probe": {},
        "budgets_requested": list(BUDGETS),
        "attempt_timeout_seconds": ATTEMPT_TIMEOUT_SECONDS,
        "attempts": [],
        "selected_num_predict": None,
        "selected_num_ctx": None,
        "selected_format_mode": None,
        "PROFILE_RESULT": "RUNNING",
    }
    _write_json(output, report)

    if not report["input_budget_pass"]:
        report["status"] = "FAIL"
        report["failure_stage"] = "input_budget"
        report["PROFILE_RESULT"] = "FAIL"
        _write_json(output, report)
        return report

    warmup = _warm_model()
    report["warmup"] = warmup
    _write_json(output, report)
    if not warmup["valid"]:
        report["status"] = "FAIL"
        report["failure_stage"] = "warmup"
        report["PROFILE_RESULT"] = "FAIL"
        _write_json(output, report)
        return report

    schema_probe = _probe_schema_support()
    report["json_schema_probe"] = schema_probe
    _write_json(output, report)
    schema_supported = bool(schema_probe["supported"])
    format_spec: str | dict[str, Any] = (
        mission_plan_json_schema(max_tasks=8)
        if schema_supported
        else "json"
    )
    report["selected_format_mode"] = (
        "json_schema" if schema_supported else "json"
    )

    for index, budget in enumerate(BUDGETS):
        num_ctx, _ = _semantic_context_window(prompt, num_predict=budget)
        report["current_num_predict"] = budget
        report["current_num_ctx"] = num_ctx
        _write_json(output, report)
        attempt = _run_streaming_attempt(
            prompt,
            num_predict=budget,
            num_ctx=num_ctx,
            format_spec=format_spec,
            attempt_index=index,
        )
        report["attempts"].append(attempt)
        _write_json(output, report)

        if attempt["valid_sufficient_plan"]:
            report["selected_num_predict"] = budget
            report["selected_num_ctx"] = num_ctx
            report["status"] = "PASS"
            report["PROFILE_RESULT"] = "PASS"
            break

        if (
            attempt["timed_out"]
            and attempt["time_to_first_token_seconds"] is None
            and int(attempt["response_content_bytes"] or 0) == 0
        ):
            report["status"] = "FAIL"
            report["failure_stage"] = "pre_first_token_prompt_eval_bound"
            report["PROFILE_RESULT"] = "FAIL"
            break

    if report["selected_num_predict"] is None:
        report["status"] = "FAIL"
        report.setdefault("failure_stage", "bounded_budget_search")
        report["PROFILE_RESULT"] = "FAIL"

    _write_json(output, report)

    print("PROMPT_BYTES=" + str(report["prompt_bytes"]))
    print("PROMPT_TOKEN_ESTIMATE=" + str(report["prompt_token_estimate"]))
    print(
        "INPUT_BUDGET_PASS="
        + ("PASS" if report["input_budget_pass"] else "FAIL")
    )
    print("CONTEXT_CAPABILITIES=" + str(report["context_capabilities"]))
    print("WARMUP_VALID=" + ("PASS" if warmup["valid"] else "FAIL"))
    print(
        "OLLAMA_JSON_SCHEMA_SUPPORTED="
        + ("PASS" if schema_supported else "FAIL")
    )
    for attempt in report["attempts"]:
        prefix = "BUDGET_" + str(attempt["num_predict"])
        print(prefix + "_NUM_CTX=" + str(attempt["num_ctx"]))
        print(prefix + "_LATENCY_SECONDS=" + f"{float(attempt['inference_latency_seconds']):.3f}")
        print(prefix + "_TTFT_SECONDS=" + str(attempt["time_to_first_token_seconds"]))
        print(prefix + "_PROMPT_EVAL_SECONDS=" + str(attempt["prompt_eval_duration_seconds"]))
        print(prefix + "_PROMPT_EVAL_TOKENS_PER_SECOND=" + str(attempt["prompt_eval_tokens_per_second"]))
        print(prefix + "_GENERATION_SECONDS=" + str(attempt["eval_duration_seconds"]))
        print(prefix + "_GENERATION_TOKENS_PER_SECOND=" + str(attempt["generation_tokens_per_second"]))
        print(prefix + "_GENERATED_TOKENS=" + str(attempt["eval_count"]))
        print(prefix + "_FINISH_REASON=" + str(attempt["finish_reason"]))
        print(prefix + "_OUTPUT_TRUNCATED=" + ("YES" if attempt["output_truncated"] else "NO"))
        print(prefix + "_STRICT_JSON_VALID=" + ("PASS" if attempt["strict_json_valid"] else "FAIL"))
        print(prefix + "_MISSION_PLAN_SCHEMA_VALID=" + ("PASS" if attempt["mission_plan_schema_valid"] else "FAIL"))
        print(prefix + "_FULL_REGISTRY_VALIDATION=" + ("PASS" if attempt["full_registry_validation"] else "FAIL"))
    print("SELECTED_NUM_PREDICT=" + str(report["selected_num_predict"]))
    print("SELECTED_NUM_CTX=" + str(report["selected_num_ctx"]))
    print("SELECTED_FORMAT_MODE=" + str(report["selected_format_mode"]))
    print("PROFILE_RESULT=" + report["PROFILE_RESULT"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/semantic-optimized-profile/optimized-profile.json",
    )
    args = parser.parse_args()
    report = run(Path(args.output))
    return 0 if report["PROFILE_RESULT"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
