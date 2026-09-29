from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.verify_telegram_a15_runtime_attestation import validate_attestation


SHA = "a" * 40
NOW = datetime(2026, 9, 29, 17, 0, 0, tzinfo=timezone.utc)


def _payload(*, state: str = "success", age_seconds: int = 30, description: str | None = None):
    prefix = SHA[:12]
    return {
        "statuses": [
            {
                "context": "telegram-a15-runtime",
                "state": state,
                "description": description
                or f"pid=123 instances=1 local={prefix} runtime={prefix} remote={prefix}",
                "updated_at": (NOW - timedelta(seconds=age_seconds)).isoformat(),
            }
        ]
    }


def test_exact_fresh_singleton_attestation_passes():
    proof = validate_attestation(
        _payload(),
        expected_sha=SHA,
        now=NOW,
        max_age_seconds=180,
    )
    assert proof["state"] == "success"
    assert proof["instances"] == 1
    assert proof["age_seconds"] == 30


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"statuses": []}, "A15_RUNTIME_ATTESTATION_MISSING"),
        (_payload(state="failure"), "A15_RUNTIME_ATTESTATION_NOT_SUCCESS"),
        (_payload(age_seconds=181), "A15_RUNTIME_ATTESTATION_STALE"),
        (
            _payload(
                description=(
                    "pid=123 instances=2 local=aaaaaaaaaaaa "
                    "runtime=aaaaaaaaaaaa remote=aaaaaaaaaaaa"
                )
            ),
            "A15_RUNTIME_ATTESTATION_IDENTITY_MISMATCH:instances",
        ),
        (
            _payload(
                description=(
                    "pid=123 instances=1 local=bbbbbbbbbbbb "
                    "runtime=aaaaaaaaaaaa remote=aaaaaaaaaaaa"
                )
            ),
            "A15_RUNTIME_ATTESTATION_IDENTITY_MISMATCH:local",
        ),
    ],
)
def test_invalid_runtime_attestation_fails_closed(payload, error):
    with pytest.raises(RuntimeError, match=error):
        validate_attestation(
            payload,
            expected_sha=SHA,
            now=NOW,
            max_age_seconds=180,
        )
