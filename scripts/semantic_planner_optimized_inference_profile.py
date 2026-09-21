from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import threading
import time
from typing import Any

from app.services.harness_adaptive_planning_service import proposal_registry_errors
from app.services.local_openweight_ai_provider import (
    _SEMANTIC_PLANNER_NUM_PREDICT,
    _semantic_context_window,
)
from app.services.semantic_mission_planner_service import (
    MissionPlanProposal,
    _json_object,
    build_semantic_planner_prompt,
)
from scripts.semantic_planner_inference_profile import (
    _json_bytes,
    _sample_resources,
    _semantic_context,
)


TIMEOUT_SECONDS = 300


def _rate(count: Any, duration_ns: Any) -> float | None:
    if not isinstance(count, int) or not isinstance(duration_ns, int) or duration_ns <= 0:
        return None
    return float(count) / (float(duration_ns) / 1_000_000_000.0)


def run(output: Path) -> dict[str, Any]:
    context = _semantic_context()
    prompt = build_semantic_planner_prompt(context)
    num_predict = _SEMANTIC_PLANNER_NUM_PREDICT
    num_ctx, prompt_estimate = _semantic_context_window(
        prompt,
        num_predict=num_predict,
    )
    payload = {
        "model": "qwen3:4b-instruct",
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "format": "json",
        "options": {
            "temperature": 0.1,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }
    payload_path = Path("/tmp/semantic-optimized-profile.json")
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
            str(TIMEOUT_SECONDS),
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
    json_valid = False
    registry_valid = False
    validation_errors: list[str] = []
    parse_error = None
    if text:
        try:
            mapping = _json_object(text)
            proposal = MissionPlanProposal.from_mapping(mapping, max_tasks=8)
            json_valid = True
            validation_errors = list(proposal_registry_errors(proposal))
            registry_valid = not validation_errors
        except Exception as exc:
            parse_error = f"{type(exc).__name__}:{exc}"[:1200]

    prompt_eval_count = final.get("prompt_eval_count")
    eval_count = final.get("eval_count")
    prompt_eval_duration = final.get("prompt_eval_duration")
    eval_duration = final.get("eval_duration")

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
    retrieval = dict(context.get("context_retrieval_evidence") or {})
    report = {
        "profile_kind": "OPTIMIZED_STREAMING_SEMANTIC_INFERENCE",
        "prompt_bytes": len(prompt.encode("utf-8")),
        "prompt_token_estimate": prompt_estimate,
        "context_capabilities": len(context.get("registry_summary") or ()),
        "context_retrieval": retrieval,
        "context_block_bytes": {
            key: _json_bytes(context.get(key)) for key in block_keys
        },
        "num_ctx": num_ctx,
        "num_predict": num_predict,
        "structured_json_mode": True,
        "return_code": return_code,
        "timed_out": return_code == 28,
        "stderr": stderr[-1200:],
        "event_count": event_count,
        "inference_latency_seconds": latency,
        "time_to_first_token_seconds": first_token_seconds,
        "response_content_bytes": len(text.encode("utf-8")),
        "thinking_bytes": len("".join(thinking_parts).encode("utf-8")),
        "prompt_tokens": prompt_eval_count,
        "generation_tokens": eval_count,
        "prompt_eval_duration_seconds": (
            float(prompt_eval_duration) / 1_000_000_000.0
            if isinstance(prompt_eval_duration, int) else None
        ),
        "generation_duration_seconds": (
            float(eval_duration) / 1_000_000_000.0
            if isinstance(eval_duration, int) else None
        ),
        "prompt_eval_tokens_per_second": _rate(
            prompt_eval_count, prompt_eval_duration
        ),
        "generation_tokens_per_second": _rate(eval_count, eval_duration),
        "semantic_plan_json_valid": json_valid,
        "registry_validation": registry_valid,
        "validation_errors": validation_errors,
        "parse_error": parse_error,
        **resources,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for key in (
        "prompt_bytes",
        "prompt_token_estimate",
        "context_capabilities",
        "num_ctx",
        "num_predict",
        "inference_latency_seconds",
        "time_to_first_token_seconds",
        "prompt_tokens",
        "generation_tokens",
        "prompt_eval_tokens_per_second",
        "generation_tokens_per_second",
        "peak_rss_mb",
        "peak_ollama_cpu_percent",
    ):
        print(key.upper() + "=" + str(report.get(key)))
    print("SEMANTIC_PLAN_JSON_VALID=" + ("PASS" if json_valid else "FAIL"))
    print("REGISTRY_VALIDATION=" + ("PASS" if registry_valid else "FAIL"))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/semantic-optimized-profile/optimized-profile.json",
    )
    args = parser.parse_args()
    run(Path(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
