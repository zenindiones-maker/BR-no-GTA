from app.services.opencode_native_ai_provider import (
    _json_candidate_is_complete,
    _recoverable_missing_finish_reason,
)


def _missing_finish_event() -> str:
    return (
        "{'type': 'provider.invalid-output', "
        "'message': 'OpenAI Chat stream ended without finish_reason', 'status': 200}"
    )


def test_missing_finish_reason_recovery_requires_complete_json():
    assert _recoverable_missing_finish_reason(
        answer='{"hook":"ok","development":[]}',
        error_events=[_missing_finish_event()],
        returncode=1,
    ) is True


def test_missing_finish_reason_recovery_rejects_partial_json():
    assert _recoverable_missing_finish_reason(
        answer='{"hook":"cut off"',
        error_events=[_missing_finish_event()],
        returncode=1,
    ) is False


def test_missing_finish_reason_recovery_rejects_other_provider_errors():
    assert _recoverable_missing_finish_reason(
        answer='{"hook":"ok"}',
        error_events=[
            "{'type': 'provider.auth', 'message': 'forbidden', 'status': 403}"
        ],
        returncode=1,
    ) is False


def test_complete_json_candidate_accepts_fenced_json_without_mutating_output():
    assert _json_candidate_is_complete('''```json
{"title":"ok"}
```''') is True
    assert _json_candidate_is_complete("not json") is False
