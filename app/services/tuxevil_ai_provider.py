import json
import os
from urllib import error, request

from app.services.ai_provider import AIProviderError, AIResponse, AIUsage


_RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _responses_text(data):
    if not isinstance(data, dict):
        return ""
    direct = data.get("output_text")
    if isinstance(direct, str):
        return direct.strip()
    output = data.get("output")
    if not isinstance(output, list):
        return ""
    chunks = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
    return "\n".join(chunks).strip()


class TuxevilAIProvider:
    """Harness-routed Tuxevil provider using the runtime-proven Responses transport."""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 90.0,
        max_retries: int = 1,
    ):
        self.model = model or os.getenv("BR_AI_MODEL", "gemini-3-flash")
        runtime_base = str(os.getenv("BR_CODEX_TUXEVIL_BASE_URL") or "").strip()
        legacy_url = str(os.getenv("BR_AI_GATEWAY_URL") or "").strip()
        if base_url:
            resolved_url = str(base_url).rstrip("/")
        elif runtime_base:
            root = runtime_base.rstrip("/")
            resolved_url = root if root.endswith("/responses") else root + "/responses"
        elif legacy_url:
            resolved_url = legacy_url.rstrip("/")
        else:
            resolved_url = "http://127.0.0.1:51200/v1/responses"
        self.base_url = resolved_url
        self.transport = (
            "tuxevil_responses"
            if self.base_url.endswith("/responses")
            else "tuxevil_chat_completions"
        )
        self.api_key = (
            api_key
            if api_key is not None
            else os.getenv("BR_TUXEVIL_LOOPBACK_KEY")
            or os.getenv("BR_AI_GATEWAY_API_KEY")
            or "tuxevil"
        )
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        if self.max_retries not in (0, 1):
            raise ValueError("Tuxevil max_retries must be 0 or 1")
        self.last_retry_count = 0
        self.last_performance_metrics = {}

    def _payload(self, prompt: str) -> dict:
        if self.transport == "tuxevil_responses":
            return {
                "model": self.model,
                "input": prompt,
                "store": False,
                "stream": False,
            }
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }

    def _error(
        self,
        message: str,
        *,
        code: str,
        status_code: int | None = None,
        retryable: bool = False,
        failure_stage: str,
        response_present: bool | None,
        structured_output_present: bool | None,
        parse_stage: str,
        exception_class: str,
        sanitized_reason: str,
    ) -> AIProviderError:
        return AIProviderError(
            message,
            code=code,
            status_code=status_code,
            retryable=retryable,
            failure_pattern=f"tuxevil_{sanitized_reason}",
            failure_stage=failure_stage,
            transport=self.transport,
            response_present=response_present,
            structured_output_present=structured_output_present,
            parse_stage=parse_stage,
            exception_class=exception_class,
            sanitized_reason=sanitized_reason,
        )

    def generate(self, prompt: str) -> AIResponse:
        if not prompt or not prompt.strip():
            raise AIProviderError(
                "Prompt must not be empty.",
                code="invalid_request",
                retryable=False,
                failure_stage="request_validation",
                transport=self.transport,
                response_present=False,
                structured_output_present=False,
                parse_stage="preflight",
                exception_class="ValueError",
                sanitized_reason="empty_prompt",
            )

        payload = json.dumps(self._payload(prompt), separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = request.Request(self.base_url, data=payload, headers=headers, method="POST")

        raw_body = ""
        self.last_retry_count = 0
        for attempt in range(self.max_retries + 1):
            try:
                with request.urlopen(req, timeout=self.timeout) as response:
                    raw_body = response.read().decode("utf-8")
                break
            except error.HTTPError as exc:
                raw = exc.read()
                structured = False
                try:
                    json.loads(raw.decode("utf-8", errors="replace"))
                    structured = True
                except Exception:
                    structured = False
                retryable = int(exc.code) in _RETRYABLE_HTTP_STATUS
                provider_error = self._error(
                    f"Tuxevil {self.transport} returned HTTP {int(exc.code)}.",
                    code="http_error",
                    status_code=int(exc.code),
                    retryable=retryable,
                    failure_stage="transport_response",
                    response_present=True,
                    structured_output_present=structured,
                    parse_stage="http_status",
                    exception_class="HTTPError",
                    sanitized_reason=f"http_{int(exc.code)}",
                )
                if retryable and attempt < self.max_retries:
                    self.last_retry_count += 1
                    continue
                raise provider_error from exc
            except TimeoutError as exc:
                provider_error = self._error(
                    "Tuxevil provider request timed out.",
                    code="timeout",
                    retryable=True,
                    failure_stage="transport_request",
                    response_present=False,
                    structured_output_present=False,
                    parse_stage="transport",
                    exception_class="TimeoutError",
                    sanitized_reason="timeout",
                )
                if attempt < self.max_retries:
                    self.last_retry_count += 1
                    continue
                raise provider_error from exc
            except error.URLError as exc:
                provider_error = self._error(
                    "Could not reach Tuxevil provider transport.",
                    code="connection_error",
                    retryable=True,
                    failure_stage="transport_request",
                    response_present=False,
                    structured_output_present=False,
                    parse_stage="transport",
                    exception_class="URLError",
                    sanitized_reason="connection_error",
                )
                if attempt < self.max_retries:
                    self.last_retry_count += 1
                    continue
                raise provider_error from exc
            except OSError as exc:
                provider_error = self._error(
                    "Tuxevil provider connection failed.",
                    code="connection_error",
                    retryable=True,
                    failure_stage="transport_request",
                    response_present=False,
                    structured_output_present=False,
                    parse_stage="transport",
                    exception_class=type(exc).__name__,
                    sanitized_reason="connection_error",
                )
                if attempt < self.max_retries:
                    self.last_retry_count += 1
                    continue
                raise provider_error from exc

        self.last_performance_metrics = {
            "transport": self.transport,
            "timeout_seconds": self.timeout,
            "retry_count": self.last_retry_count,
        }

        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise self._error(
                "Tuxevil provider returned invalid JSON.",
                code="invalid_json",
                retryable=False,
                failure_stage="response_decode",
                response_present=True,
                structured_output_present=False,
                parse_stage="json_decode",
                exception_class="JSONDecodeError",
                sanitized_reason="invalid_json",
            ) from exc

        if self.transport == "tuxevil_responses":
            text = _responses_text(data)
            parse_stage = "responses_output_text"
        else:
            try:
                text = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise self._error(
                    "Tuxevil provider returned an invalid chat completion.",
                    code="invalid_response_shape",
                    retryable=False,
                    failure_stage="response_extract",
                    response_present=True,
                    structured_output_present=True,
                    parse_stage="chat_completion_content",
                    exception_class=type(exc).__name__,
                    sanitized_reason="invalid_chat_completion",
                ) from exc
            parse_stage = "chat_completion_content"

        if not isinstance(text, str) or not text.strip():
            raise self._error(
                "Tuxevil provider returned an empty response.",
                code="empty_response",
                retryable=False,
                failure_stage="response_extract",
                response_present=True,
                structured_output_present=isinstance(data, dict),
                parse_stage=parse_stage,
                exception_class="EmptyProviderResponse",
                sanitized_reason="empty_response",
            )

        usage_data = data.get("usage") if isinstance(data, dict) else None
        usage = None
        if isinstance(usage_data, dict):
            prompt_tokens = usage_data.get("input_tokens", usage_data.get("prompt_tokens"))
            completion_tokens = usage_data.get("output_tokens", usage_data.get("completion_tokens"))
            total_tokens = usage_data.get("total_tokens")
            usage = AIUsage(
                prompt_tokens=int(prompt_tokens) if isinstance(prompt_tokens, int) else None,
                completion_tokens=int(completion_tokens) if isinstance(completion_tokens, int) else None,
                total_tokens=int(total_tokens) if isinstance(total_tokens, int) else None,
            )

        return AIResponse(
            text=text.strip(),
            provider="tuxevil",
            model=self.model,
            usage=usage,
            finish_reason=(
                str(data.get("status"))
                if self.transport == "tuxevil_responses"
                and isinstance(data, dict)
                and data.get("status") is not None
                else None
            ),
        )
