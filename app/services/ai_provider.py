from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AIUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None


@dataclass(frozen=True)
class AIResponse:
    text: str
    provider: str | None = None
    model: str | None = None
    reasoning_content: str | None = None
    usage: AIUsage | None = None
    finish_reason: str | None = None


class AIProviderError(RuntimeError):
    """Structured, audit-safe base error for AI provider failures."""

    _SENSITIVE_TERMS = (
        "authorization",
        "api_key",
        "apikey",
        "token",
        "bearer",
        "refresh_token",
        "client_secret",
    )

    def __init__(
        self,
        message: str,
        *,
        code: str = "provider_error",
        status_code: int | None = None,
        retryable: bool = False,
        failure_pattern: str | None = None,
        failure_stage: str | None = None,
        transport: str | None = None,
        response_present: bool | None = None,
        structured_output_present: bool | None = None,
        parse_stage: str | None = None,
        exception_class: str | None = None,
        sanitized_reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code or "provider_error")
        self.status_code = status_code
        self.retryable = bool(retryable)
        self.failure_pattern = failure_pattern
        self.failure_stage = failure_stage
        self.transport = transport
        self.response_present = response_present
        self.structured_output_present = structured_output_present
        self.parse_stage = parse_stage
        self.exception_class = str(exception_class or type(self).__name__)
        self.sanitized_reason = str(sanitized_reason or self.code)
        self.safe_message = self._sanitize_message(message)

    @classmethod
    def _sanitize_message(cls, value: str) -> str:
        text = str(value or "AIProviderError")
        lowered = text.casefold()
        if any(term in lowered for term in cls._SENSITIVE_TERMS):
            return "AI provider request failed."
        return text[:1200]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "message": self.safe_message,
            "error_type": self.exception_class,
            "failure_pattern": self.failure_pattern,
            "failure_stage": self.failure_stage,
            "transport": self.transport,
            "response_present": self.response_present,
            "structured_output_present": self.structured_output_present,
            "parse_stage": self.parse_stage,
            "sanitized_reason": self.sanitized_reason,
        }


class AIProvider(Protocol):
    def generate(self, prompt: str) -> AIResponse:
        """Generate a response from a text prompt."""
        ...
