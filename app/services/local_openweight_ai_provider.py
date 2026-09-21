from __future__ import annotations

import json
import os
import time
from urllib import error, parse, request

from app.services.ai_provider import AIProviderError, AIResponse, AIUsage


LOCAL_OPENWEIGHT_PROVIDER_ID = "ollama_local"
LOCAL_OPENWEIGHT_MODEL_ID = "qwen3:4b-instruct"
LOCAL_OPENWEIGHT_MODEL_DIGEST = (
    "0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0"
)
LOCAL_OPENWEIGHT_OLLAMA_VERSION = "0.34.2"

_SEMANTIC_PLANNER_NUM_PREDICT = 900
_SEMANTIC_CONTEXT_BUCKETS = (8192, 12288, 16384, 24576, 32768)
_SEMANTIC_PLANNER_PROFILE_BUDGETS = (256, 384, 512, 900)


def semantic_planner_num_predict() -> int:
    raw = str(os.getenv("BR_LOCAL_SEMANTIC_NUM_PREDICT") or "").strip()
    if not raw:
        return _SEMANTIC_PLANNER_NUM_PREDICT
    try:
        value = int(raw)
    except ValueError as exc:
        raise AIProviderError(
            "Invalid bounded local semantic output budget."
        ) from exc
    if value not in _SEMANTIC_PLANNER_PROFILE_BUDGETS:
        raise AIProviderError(
            "Local semantic output budget is outside profiled bounds."
        )
    return value


def _seconds_from_ns(value):
    if not isinstance(value, int):
        return None
    return float(value) / 1_000_000_000.0


def _rate(count, duration_ns):
    seconds = _seconds_from_ns(duration_ns)
    if not isinstance(count, int) or not seconds:
        return None
    return float(count) / seconds


def _is_structured_semantic_planner_prompt(value: str) -> bool:
    return (
        "MissionPlan only" in value
        and "OUTPUT_CONTRACT=" in value
        and "CONTEXT=" in value
    )


def _semantic_context_window(value: str, *, num_predict: int) -> tuple[int, int]:
    # Deliberately conservative estimate. JSON-heavy prompts are usually better
    # than three characters/token; using three prevents a too-small KV context.
    estimated_prompt_tokens = max(1, (len(value) + 2) // 3)
    required = estimated_prompt_tokens + int(num_predict) + 1024
    for bucket in _SEMANTIC_CONTEXT_BUCKETS:
        if required <= bucket:
            return bucket, estimated_prompt_tokens
    raise AIProviderError(
        "Semantic planner prompt exceeds bounded local context window."
    )


class OllamaLocalAIProvider:
    """Bounded local semantic provider proven on standard public GitHub Actions."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str | None = None,
        timeout: float = 300.0,
    ) -> None:
        if model != LOCAL_OPENWEIGHT_MODEL_ID:
            raise PermissionError("local open-weight provider model identity mismatch")
        root = (
            base_url
            or os.getenv("BR_LOCAL_OPENWEIGHT_URL")
            or "http://127.0.0.1:11434"
        ).rstrip("/")
        parsed = parse.urlparse(root)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise PermissionError("local open-weight provider must remain loopback-only")
        self.model = model
        self.base_url = root
        self.timeout = timeout
        self.executor_binding = (
            "app.services.local_openweight_ai_provider.OllamaLocalAIProvider"
        )
        self.last_performance_metrics: dict[str, object] = {}

    def generate(self, prompt: str) -> AIResponse:
        value = str(prompt or "").strip()
        if not value:
            raise AIProviderError("Prompt must not be empty.")

        structured_planner = _is_structured_semantic_planner_prompt(value)
        if structured_planner:
            num_predict = semantic_planner_num_predict()
            num_ctx, prompt_token_estimate = _semantic_context_window(
                value,
                num_predict=num_predict,
            )
        else:
            # Preserve established behavior for other Harness callers.
            num_predict = 1800
            num_ctx = 32768
            prompt_token_estimate = max(1, (len(value) + 2) // 3)

        request_body = {
            "model": self.model,
            "messages": [{"role": "user", "content": value}],
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
            },
        }
        schema_mode = (
            structured_planner
            and str(os.getenv("BR_LOCAL_SEMANTIC_SCHEMA") or "").strip()
            in {"1", "true", "TRUE", "yes", "YES"}
        )
        if schema_mode:
            from app.services.semantic_mission_planner_service import (
                mission_plan_json_schema,
            )
            request_body["format"] = mission_plan_json_schema(max_tasks=8)
        elif structured_planner:
            # JSON mode remains the safe fallback until schema support is
            # operationally proven on the pinned Ollama runtime.
            request_body["format"] = "json"

        payload = json.dumps(
            request_body,
            ensure_ascii=False,
        ).encode("utf-8")
        req = request.Request(
            self.base_url + "/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        self.last_performance_metrics = {
            "prompt_bytes": len(value.encode("utf-8")),
            "prompt_token_estimate": prompt_token_estimate,
            "requested_output_tokens": num_predict,
            "num_ctx": num_ctx,
            "structured_json_mode": structured_planner,
            "structured_json_schema_mode": schema_mode,
            "timeout_seconds": self.timeout,
        }
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            self.last_performance_metrics["latency_seconds"] = (
                time.perf_counter() - started
            )
            body = exc.read().decode("utf-8", errors="replace")
            raise AIProviderError(
                f"Local Ollama provider returned HTTP {exc.code}: {body[:800]}"
            ) from exc
        except error.URLError as exc:
            self.last_performance_metrics["latency_seconds"] = (
                time.perf_counter() - started
            )
            raise AIProviderError(
                f"Local Ollama provider is unavailable: {exc.reason}"
            ) from exc
        except (TimeoutError, OSError) as exc:
            self.last_performance_metrics["latency_seconds"] = (
                time.perf_counter() - started
            )
            raise AIProviderError(
                f"Local Ollama provider execution failed: {exc}"
            ) from exc

        try:
            data = json.loads(raw)
            message = data.get("message")
            text = (
                str(message.get("content") or "").strip()
                if isinstance(message, dict)
                else ""
            )
        except (json.JSONDecodeError, TypeError) as exc:
            self.last_performance_metrics["latency_seconds"] = (
                time.perf_counter() - started
            )
            raise AIProviderError("Local Ollama provider returned invalid JSON.") from exc
        if not text:
            self.last_performance_metrics["latency_seconds"] = (
                time.perf_counter() - started
            )
            raise AIProviderError("Local Ollama provider returned empty text.")

        prompt_tokens = data.get("prompt_eval_count")
        completion_tokens = data.get("eval_count")
        total_tokens = None
        if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
            total_tokens = prompt_tokens + completion_tokens

        prompt_eval_duration = data.get("prompt_eval_duration")
        eval_duration = data.get("eval_duration")
        finish_reason = str(data.get("done_reason") or "stop")
        output_truncated = bool(
            finish_reason == "length"
            or (
                isinstance(completion_tokens, int)
                and completion_tokens >= num_predict
                and finish_reason != "stop"
            )
        )
        self.last_performance_metrics.update({
            "latency_seconds": time.perf_counter() - started,
            "finish_reason": finish_reason,
            "output_truncated": output_truncated,
            "ollama_total_duration_seconds": _seconds_from_ns(
                data.get("total_duration")
            ),
            "ollama_load_duration_seconds": _seconds_from_ns(
                data.get("load_duration")
            ),
            "prompt_eval_duration_seconds": _seconds_from_ns(
                prompt_eval_duration
            ),
            "eval_duration_seconds": _seconds_from_ns(eval_duration),
            "prompt_eval_tokens": (
                prompt_tokens if isinstance(prompt_tokens, int) else None
            ),
            "generation_tokens": (
                completion_tokens if isinstance(completion_tokens, int) else None
            ),
            "prompt_eval_tokens_per_second": _rate(
                prompt_tokens, prompt_eval_duration
            ),
            "generation_tokens_per_second": _rate(
                completion_tokens, eval_duration
            ),
        })

        return AIResponse(
            text=text,
            provider=LOCAL_OPENWEIGHT_PROVIDER_ID,
            model=self.model,
            usage=AIUsage(
                prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
                completion_tokens=(
                    completion_tokens if isinstance(completion_tokens, int) else None
                ),
                total_tokens=total_tokens,
            ),
            finish_reason=finish_reason,
        )
