from __future__ import annotations

import json
import os
from socket import timeout as SocketTimeout
from typing import Any
from urllib import error, request

from app.services.ai_provider import AIProviderError, AIResponse, AIUsage


DEFAULT_NVIDIA_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_NVIDIA_NIM_MODEL = "nvidia/nemotron-3-super-120b-a12b"
DEFAULT_NVIDIA_NIM_TIMEOUT_SECONDS = 120.0


class NvidiaNIMProviderError(AIProviderError):
    """Structured, secret-safe NVIDIA NIM provider error."""

    def __init__(
        self,
        safe_message: str,
        *,
        code: str,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.provider = "nvidia_nim"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "code": self.code,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "message": self.safe_message,
        }


class NvidiaNIMProvider:
    """OpenAI-compatible NVIDIA NIM adapter for the BR AIProvider contract."""

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.model = model or os.getenv("NVIDIA_NIM_MODEL") or DEFAULT_NVIDIA_NIM_MODEL
        self.base_url = (
            base_url
            or os.getenv("NVIDIA_NIM_BASE_URL")
            or DEFAULT_NVIDIA_NIM_BASE_URL
        )
        self._api_key = api_key if api_key is not None else os.getenv("NVIDIA_API_KEY")
        configured_timeout = os.getenv("NVIDIA_NIM_TIMEOUT_SECONDS")
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else float(configured_timeout or DEFAULT_NVIDIA_NIM_TIMEOUT_SECONDS)
        )

    def generate(self, prompt: str) -> AIResponse:
        if not prompt or not prompt.strip():
            raise NvidiaNIMProviderError(
                "Prompt must not be empty",
                code="invalid_prompt",
            )
        if not self._api_key:
            raise NvidiaNIMProviderError(
                "NVIDIA_API_KEY is required when NVIDIA NIM is selected",
                code="missing_api_key",
            )

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            self.base_url,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )

        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                raw_payload = response.read()
        except error.HTTPError as exc:
            raise self._http_error(exc.code) from None
        except (TimeoutError, SocketTimeout):
            raise NvidiaNIMProviderError(
                "NVIDIA NIM request timed out",
                code="timeout",
                retryable=True,
            ) from None
        except error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, SocketTimeout)):
                raise NvidiaNIMProviderError(
                    "NVIDIA NIM request timed out",
                    code="timeout",
                    retryable=True,
                ) from None
            raise NvidiaNIMProviderError(
                "NVIDIA NIM transport failed",
                code="transport_error",
                retryable=True,
            ) from None
        except OSError:
            raise NvidiaNIMProviderError(
                "NVIDIA NIM transport failed",
                code="transport_error",
                retryable=True,
            ) from None

        try:
            data = json.loads(raw_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise NvidiaNIMProviderError(
                "NVIDIA NIM returned invalid JSON",
                code="invalid_json",
            ) from None

        try:
            choice = data["choices"][0]
            message = choice["message"]
            text = message["content"]
        except (KeyError, IndexError, TypeError):
            raise NvidiaNIMProviderError(
                "NVIDIA NIM returned an invalid chat completion",
                code="invalid_completion",
            ) from None

        if not isinstance(text, str) or not text.strip():
            raise NvidiaNIMProviderError(
                "NVIDIA NIM returned an empty response",
                code="empty_response",
            )

        reasoning_content = message.get("reasoning_content")
        if not isinstance(reasoning_content, str):
            reasoning_content = None

        return AIResponse(
            text=text,
            provider="nvidia_nim",
            model=data.get("model") or self.model,
            reasoning_content=reasoning_content,
            usage=self._normalize_usage(data.get("usage")),
            finish_reason=choice.get("finish_reason"),
        )

    @staticmethod
    def _normalize_usage(raw_usage: Any) -> AIUsage | None:
        if not isinstance(raw_usage, dict):
            return None
        details = raw_usage.get("completion_tokens_details")
        reasoning_tokens = (
            details.get("reasoning_tokens")
            if isinstance(details, dict)
            else None
        )
        return AIUsage(
            prompt_tokens=NvidiaNIMProvider._optional_int(raw_usage.get("prompt_tokens")),
            completion_tokens=NvidiaNIMProvider._optional_int(raw_usage.get("completion_tokens")),
            total_tokens=NvidiaNIMProvider._optional_int(raw_usage.get("total_tokens")),
            reasoning_tokens=NvidiaNIMProvider._optional_int(reasoning_tokens),
        )

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @staticmethod
    def _http_error(status_code: int) -> NvidiaNIMProviderError:
        mapping = {
            401: ("authentication_failed", "NVIDIA NIM authentication failed", False),
            403: ("forbidden", "NVIDIA NIM request was forbidden", False),
            410: ("gone", "NVIDIA NIM endpoint or model is no longer available", False),
            422: ("invalid_request", "NVIDIA NIM rejected the request", False),
            429: ("rate_limited", "NVIDIA NIM rate limit exceeded", True),
        }
        if status_code in mapping:
            code, message, retryable = mapping[status_code]
        elif 500 <= status_code <= 599:
            code, message, retryable = (
                "upstream_error",
                "NVIDIA NIM upstream service failed",
                True,
            )
        else:
            code, message, retryable = (
                "http_error",
                "NVIDIA NIM request failed",
                False,
            )
        return NvidiaNIMProviderError(
            message,
            code=code,
            status_code=status_code,
            retryable=retryable,
        )

    def safe_configuration(self) -> dict[str, Any]:
        """Expose diagnostics without ever returning credentials."""
        return {
            "provider": "nvidia_nim",
            "base_url": self.base_url,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "api_key_configured": bool(self._api_key),
        }
