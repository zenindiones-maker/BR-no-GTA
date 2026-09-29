from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Any

CONTEXT = "telegram-a15-runtime"


def _timestamp(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("runtime attestation has no timestamp")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _description_fields(description: Any) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in str(description or "").split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if key and value:
            fields[key] = value
    return fields


def validate_attestation(
    payload: dict[str, Any],
    *,
    expected_sha: str,
    now: datetime,
    max_age_seconds: int,
) -> dict[str, Any]:
    expected = str(expected_sha or "").strip().lower()
    if len(expected) < 12:
        raise ValueError("expected SHA must contain at least 12 hexadecimal characters")
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")

    statuses = payload.get("statuses")
    if not isinstance(statuses, list):
        raise RuntimeError("A15_RUNTIME_ATTESTATION_INVALID_PAYLOAD")

    candidates = [
        item
        for item in statuses
        if isinstance(item, dict) and str(item.get("context") or "") == CONTEXT
    ]
    if not candidates:
        raise RuntimeError("A15_RUNTIME_ATTESTATION_MISSING")

    candidates.sort(
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )
    status = candidates[0]
    if str(status.get("state") or "").lower() != "success":
        raise RuntimeError("A15_RUNTIME_ATTESTATION_NOT_SUCCESS")

    fields = _description_fields(status.get("description"))
    prefix = expected[:12]
    required = {
        "instances": "1",
        "local": prefix,
        "runtime": prefix,
        "remote": prefix,
    }
    for key, wanted in required.items():
        observed = str(fields.get(key) or "").lower()
        if observed != wanted:
            raise RuntimeError(
                f"A15_RUNTIME_ATTESTATION_IDENTITY_MISMATCH:{key}:{observed or 'missing'}"
            )

    updated_at = _timestamp(status.get("updated_at") or status.get("created_at"))
    age_seconds = (now.astimezone(timezone.utc) - updated_at).total_seconds()
    if age_seconds < -60:
        raise RuntimeError("A15_RUNTIME_ATTESTATION_CLOCK_SKEW")
    if age_seconds > max_age_seconds:
        raise RuntimeError(
            f"A15_RUNTIME_ATTESTATION_STALE:{int(age_seconds)}s"
        )

    return {
        "context": CONTEXT,
        "state": "success",
        "expected_sha": expected,
        "observed_prefix": prefix,
        "instances": 1,
        "updated_at": updated_at.isoformat(),
        "age_seconds": max(0, int(age_seconds)),
    }


def _fetch_status(*, repository: str, sha: str, token: str) -> dict[str, Any]:
    url = f"https://api.github.com/repos/{repository}/commits/{sha}/status"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "br-no-gta-telegram-runtime-readiness",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("A15_RUNTIME_ATTESTATION_INVALID_PAYLOAD")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument(
        "--max-age-seconds",
        type=int,
        default=int(
            os.environ.get(
                "TELEGRAM_A15_RUNTIME_ATTESTATION_MAX_AGE_SECONDS",
                "180",
            )
        ),
    )
    parser.add_argument("--status-json")
    args = parser.parse_args()

    if args.status_json:
        payload = json.loads(open(args.status_json, encoding="utf-8").read())
    else:
        if not args.repository or not args.sha:
            raise SystemExit("A15_RUNTIME_ATTESTATION_CONFIG_MISSING")
        payload = _fetch_status(
            repository=args.repository,
            sha=args.sha,
            token=os.environ.get("GITHUB_TOKEN", ""),
        )

    try:
        proof = validate_attestation(
            payload,
            expected_sha=args.sha,
            now=datetime.now(timezone.utc),
            max_age_seconds=args.max_age_seconds,
        )
    except Exception as exc:
        print(f"A15_LIVE_RUNTIME_ATTESTATION=FAIL")
        print(f"A15_RUNTIME_BLOCKER={type(exc).__name__}:{exc}")
        return 2

    print("A15_LIVE_RUNTIME_ATTESTATION=PASS")
    print(f"A15_RUNTIME_SHA={proof['expected_sha']}")
    print(f"A15_RUNTIME_INSTANCES={proof['instances']}")
    print(f"A15_RUNTIME_ATTESTATION_AGE_SECONDS={proof['age_seconds']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
