from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any
from urllib import request

from app.services.harness_adaptive_planning_service import proposal_registry_errors
from app.services.local_openweight_ai_provider import _semantic_context_window
from app.services.semantic_mission_planner_service import (
    MissionPlanProposal,
    build_semantic_planner_prompt,
    mission_plan_json_schema,
    semantic_prompt_component_bytes,
)
from scripts.semantic_planner_inference_profile import (
    _sample_resources,
    _semantic_context,
)


MODEL = "qwen3:4b-instruct"
OUTPUT_TOKEN_BUDGET = 512
ATTEMPT_TIMEOUT_SECONDS = 180
SCHEMA_PROBE_TIMEOUT_SECONDS = 90


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


def _post(payload: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    req = request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _schema_support_probe() -> dict[str, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["ok"],
        "properties": {"ok": {"type": "boolean", "const": True}},
    }
    started = time.perf_counter()
    try:
        data = _post(
            {
                "model": MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": 'Return an object with ok=true.',
                    }
                ],
                "stream": False,
                "format": schema,
                "keep_alive": "0",
                "options": {
                    "temperature": 0.0,
                    "num_ctx": 2048,
                    "num_predict": 16,
                },
            },
            timeout=SCHEMA_PROBE_TIMEOUT_SECONDS,
        )
        message = data.get("message") if isinstance(data, dict) else None
        text = str(message.get("content") or "") if isinstance(message, dict) else ""
        parsed = json.loads(text)
        supported = parsed == {"ok": True}
        return {
            "supported": supported,
            "latency_seconds": time.perf_counter() - started,
            "response": parsed if supported else None,
            "done_reason": data.get("done_reason"),
        }
    except Exception as exc:
        return {
            "supported": False,
            "latency_seconds": time.perf_counter() - started,
            "error": f"{type(exc).__name__}:{exc}"[:1200],
        }


def _restart_runtime_cold() -> dict[str, Any]:
    pid_path = Path("/tmp/ollama-optimized-profile.pid")
    if pid_path.exists():
        try:
            os.kill(int(pid_path.read_text().strip()), 15)
        except (ValueError, ProcessLookupError):
            pass
        time.sleep(2)
    subprocess.run(["pkill", "-f", "ollama serve"], check=False)
    time.sleep(1)
    log = open("/tmp/ollama-optimized-profile-cold.log", "w", encoding="utf-8")
    proc = subprocess.Popen(
        ["ollama", "serve"],
        stdout=log,
        stderr=subprocess.STDOUT,
        env={
            **os.environ,
            "OLLAMA_HOST": os.getenv("OLLAMA_HOST", "127.0.0.1:11434"),
            "OLLAMA_NO_CLOUD": "1",
        },
    )
    pid_path.write_text(str(proc.pid), encoding="utf-8")
    for _ in range(60):
        try:
            with request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1):
                return {"restarted": True, "pid": proc.pid}
        except Exception:
            time.sleep(1)
    return {"restarted": False, "pid": proc.pid}


def _run_cold_proposal(
    prompt: str,
    *,
    num_predict: int,
    num_ctx: int,
) -> dict[str, Any]:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "format": mission_plan_json_schema(max_tasks=8),
        "keep_alive": "0",
        "options": {
            "temperature": 0.1,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }
    payload_path = Path("/tmp/semantic-cold-schema.json")
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
            "curl", "--no-buffer", "--silent", "--show-error",
            "--max-time", str(ATTEMPT_TIMEOUT_SECONDS),
            "-H", "Content-Type: application/json",
            "--data-binary", "@" + str(payload_path),
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
    prompt_eval_duration = final.get("prompt_eval_duration")
    eval_duration = final.get("eval_duration")
    return {
        "cold_start_proposal": True,
        "num_predict": num_predict,
        "num_ctx": num_ctx,
        "return_code": return_code,
        "timed_out": return_code == 28,
        "stderr": stderr[-1200:],
        "inference_latency_seconds": latency,
        "time_to_first_token_seconds": first_token_seconds,
        "prompt_eval_count": final.get("prompt_eval_count"),
        "prompt_eval_duration_seconds": (
            float(prompt_eval_duration) / 1_000_000_000.0
            if isinstance(prompt_eval_duration, int) else None
        ),
        "prompt_eval_tokens_per_second": _rate(
            final.get("prompt_eval_count"), prompt_eval_duration
        ),
        "eval_count": eval_count,
        "eval_duration_seconds": (
            float(eval_duration) / 1_000_000_000.0
            if isinstance(eval_duration, int) else None
        ),
        "generation_tokens_per_second": _rate(eval_count, eval_duration),
        "finish_reason": finish_reason,
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


def run(output: Path) -> dict[str, Any]:
    context = _semantic_context()
    prompt = build_semantic_planner_prompt(context)
    num_ctx, prompt_estimate = _semantic_context_window(
        prompt,
        num_predict=OUTPUT_TOKEN_BUDGET,
    )
    component_bytes = semantic_prompt_component_bytes(context)
    instruction_bytes = len(prompt.split("\n", 1)[0].encode("utf-8"))
    report: dict[str, Any] = {
        "profile_kind": "COLD_SCHEMA_BOUNDED_MISSION_PLAN",
        "status": "RUNNING",
        "provider": "ollama_local",
        "model": MODEL,
        "prompt_bytes": len(prompt.encode("utf-8")),
        "prompt_token_estimate": prompt_estimate,
        "prompt_component_bytes": {
            "instructions": instruction_bytes,
            **component_bytes,
        },
        "context_capabilities": len(context.get("registry_summary") or ()),
        "output_token_budget": OUTPUT_TOKEN_BUDGET,
        "num_ctx": num_ctx,
        "schema_probe": {},
        "runtime_restart": {},
        "cold_proposal": {},
        "PROFILE_RESULT": "RUNNING",
    }
    _write_json(output, report)

    schema_probe = _schema_support_probe()
    report["schema_probe"] = schema_probe
    _write_json(output, report)
    if not schema_probe.get("supported"):
        report.update({
            "status": "FAIL",
            "failure_stage": "native_schema_probe",
            "PROFILE_RESULT": "FAIL",
        })
        _write_json(output, report)
        return report

    restart = _restart_runtime_cold()
    report["runtime_restart"] = restart
    _write_json(output, report)
    if not restart.get("restarted"):
        report.update({
            "status": "FAIL",
            "failure_stage": "cold_runtime_restart",
            "PROFILE_RESULT": "FAIL",
        })
        _write_json(output, report)
        return report

    proposal = _run_cold_proposal(
        prompt,
        num_predict=OUTPUT_TOKEN_BUDGET,
        num_ctx=num_ctx,
    )
    report["cold_proposal"] = proposal
    prompt_bound = prompt_estimate <= 2000
    pass_all = all((
        prompt_bound,
        proposal["return_code"] == 0,
        proposal["finish_reason"] == "stop",
        not proposal["output_truncated"],
        proposal["strict_json_valid"],
        proposal["mission_plan_schema_valid"],
        proposal["full_registry_validation"],
        float(proposal["inference_latency_seconds"]) < 180.0,
    ))
    report.update({
        "status": "PASS" if pass_all else "FAIL",
        "failure_stage": None if pass_all else "cold_single_proposal_gate",
        "prompt_token_target_pass": prompt_bound,
        "PROFILE_RESULT": "PASS" if pass_all else "FAIL",
    })
    _write_json(output, report)

    print("NATIVE_JSON_SCHEMA_SUPPORTED=" + ("PASS" if schema_probe.get("supported") else "FAIL"))
    print("COLD_START_PROPOSAL=YES")
    print("PROMPT_BYTES=" + str(report["prompt_bytes"]))
    print("PROMPT_TOKEN_ESTIMATE=" + str(prompt_estimate))
    print("PROMPT_COMPONENT_BYTES=" + json.dumps(report["prompt_component_bytes"], sort_keys=True))
    print("OUTPUT_TOKEN_BUDGET=" + str(OUTPUT_TOKEN_BUDGET))
    print("NUM_CTX=" + str(num_ctx))
    print("GENERATED_TOKENS=" + str(proposal.get("eval_count")))
    print("FINISH_REASON=" + str(proposal.get("finish_reason")))
    print("OUTPUT_TRUNCATED=" + ("YES" if proposal.get("output_truncated") else "NO"))
    print("STRICT_JSON_VALID=" + ("PASS" if proposal.get("strict_json_valid") else "FAIL"))
    print("MISSION_PLAN_SCHEMA_VALID=" + ("PASS" if proposal.get("mission_plan_schema_valid") else "FAIL"))
    print("FULL_REGISTRY_VALIDATION=" + ("PASS" if proposal.get("full_registry_validation") else "FAIL"))
    print("INFERENCE_LATENCY_SECONDS=" + f"{float(proposal.get('inference_latency_seconds') or 0.0):.3f}")
    print("PROMPT_EVAL_SECONDS=" + str(proposal.get("prompt_eval_duration_seconds")))
    print("GENERATION_SECONDS=" + str(proposal.get("eval_duration_seconds")))
    print("PEAK_RSS_MB=" + f"{float(proposal.get('peak_rss_mb') or 0.0):.3f}")
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
