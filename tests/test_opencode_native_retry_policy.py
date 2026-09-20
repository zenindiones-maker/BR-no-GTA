from app.services.opencode_native_ai_provider import (
    OpenCodeNativeAIProviderError,
    _retryable_missing_finish_reason_error,
)


def test_missing_finish_reason_http_200_is_retryable_once():
    exc = OpenCodeNativeAIProviderError(
        "transient stream termination",
        details={
            "error_events": [
                "{'type': 'provider.invalid-output', 'message': 'OpenAI Chat stream ended without finish_reason', 'status': 200}"
            ]
        },
    )
    assert _retryable_missing_finish_reason_error(exc) is True


def test_deterministic_provider_failure_is_not_retryable():
    exc = OpenCodeNativeAIProviderError(
        "deterministic failure",
        details={"error_events": ["provider.invalid-output: schema mismatch status 400"]},
    )
    assert _retryable_missing_finish_reason_error(exc) is False
