from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


INCIDENT_SCHEMA = "ContinuousOperationIncident/v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _require_attempt(value: dict[str, Any], *, label: str) -> dict[str, Any]:
    payload = dict(value or {})
    if payload.get("schema") != "ContinuousOperationAttempt/v1":
        raise ValueError(f"{label} attempt schema mismatch")
    target_sha = str(payload.get("target_sha") or "").strip().lower()
    if _SHA40.fullmatch(target_sha) is None:
        raise ValueError(f"{label} attempt target_sha must be exact")
    status = str(payload.get("status") or "").strip()
    if status not in {"PASS", "FAIL", "HELD_KNOWN_DEFECT"}:
        raise ValueError(f"{label} attempt status invalid")
    if status != "PASS":
        fingerprint = str(payload.get("failure_fingerprint") or "").strip().lower()
        if _SHA256.fullmatch(fingerprint) is None:
            raise ValueError(f"{label} attempt failure_fingerprint invalid")
        if not str(payload.get("failure_class") or "").strip():
            raise ValueError(f"{label} attempt failure_class missing")
        if not str(payload.get("wake_condition") or "").strip():
            raise ValueError(f"{label} attempt wake_condition missing")
    return payload


def _prior_incident(prior_attempt: dict[str, Any] | None) -> dict[str, Any] | None:
    if prior_attempt is None:
        return None
    prior = _require_attempt(prior_attempt, label="prior")
    state = prior.get("incident_state")
    if not isinstance(state, dict):
        return None
    if state.get("schema") != INCIDENT_SCHEMA:
        return None
    fingerprint = str(state.get("incident_fingerprint") or "").strip().lower()
    target_sha = str(state.get("target_sha") or "").strip().lower()
    occurrence_count = state.get("occurrence_count")
    if (
        _SHA256.fullmatch(fingerprint) is None
        or _SHA40.fullmatch(target_sha) is None
        or not isinstance(occurrence_count, int)
        or occurrence_count < 1
    ):
        return None
    return dict(state)


def settle_incident(
    *,
    current_attempt: dict[str, Any],
    prior_attempt: dict[str, Any] | None,
) -> dict[str, Any] | None:
    current = _require_attempt(current_attempt, label="current")
    status = str(current["status"])

    if status == "PASS":
        prior_state = _prior_incident(prior_attempt)
        if prior_state is None:
            return None
        return {
            **prior_state,
            "last_seen_at": str(current.get("finished_at") or current.get("started_at") or ""),
            "current_status": "RESOLVED",
            "resolved_at": str(current.get("finished_at") or ""),
            "alert_required": False,
            "alert_reason": "RECOVERY_SETTLED_NO_DUPLICATE_ALERT",
            "wake_condition": None,
        }

    fingerprint = str(current["failure_fingerprint"]).strip().lower()
    target_sha = str(current["target_sha"]).strip().lower()
    prior_state = _prior_incident(prior_attempt)

    same_incident = (
        prior_state is not None
        and str(prior_state.get("incident_fingerprint") or "").strip().lower() == fingerprint
        and str(prior_state.get("target_sha") or "").strip().lower() == target_sha
    )

    first_seen_at = (
        str(prior_state.get("first_seen_at") or current.get("started_at") or "")
        if same_incident
        else str(current.get("started_at") or current.get("finished_at") or "")
    )
    occurrence_count = (
        int(prior_state.get("occurrence_count") or 0) + 1
        if same_incident
        else 1
    )
    current_status = "HELD_KNOWN_DEFECT" if status == "HELD_KNOWN_DEFECT" else "OPEN"

    return {
        "schema": INCIDENT_SCHEMA,
        "incident_fingerprint": fingerprint,
        "failure_class": str(current.get("failure_class") or ""),
        "first_seen_at": first_seen_at,
        "last_seen_at": str(current.get("finished_at") or current.get("started_at") or ""),
        "occurrence_count": occurrence_count,
        "current_status": current_status,
        "target_sha": target_sha,
        "wake_condition": str(current.get("wake_condition") or ""),
        "causal_task_id": current.get("causal_task_id"),
        "causal_step": str(current.get("causal_step") or ""),
        "retryability": str(current.get("retryability") or ""),
        "alert_required": not same_incident,
        "alert_reason": (
            "DUPLICATE_SAME_FINGERPRINT_SUPPRESSED"
            if same_incident
            else "NEW_ACTIONABLE_INCIDENT"
        ),
    }


def settle_attempt_file(
    *,
    current_attempt_path: Path,
    prior_attempt_path: Path | None = None,
    incident_output_path: Path | None = None,
) -> dict[str, Any] | None:
    current = json.loads(current_attempt_path.read_text(encoding="utf-8"))
    prior = None
    if prior_attempt_path is not None and prior_attempt_path.is_file():
        prior = json.loads(prior_attempt_path.read_text(encoding="utf-8"))

    incident = settle_incident(current_attempt=current, prior_attempt=prior)
    if incident is not None:
        current["incident_state"] = incident
        current_attempt_path.write_text(
            json.dumps(current, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        if incident_output_path is not None:
            incident_output_path.parent.mkdir(parents=True, exist_ok=True)
            incident_output_path.write_text(
                json.dumps(incident, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
    return incident


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-attempt", required=True)
    parser.add_argument("--prior-attempt")
    parser.add_argument("--incident-output")
    args = parser.parse_args()

    incident = settle_attempt_file(
        current_attempt_path=Path(args.current_attempt),
        prior_attempt_path=Path(args.prior_attempt) if args.prior_attempt else None,
        incident_output_path=Path(args.incident_output) if args.incident_output else None,
    )
    if incident is None:
        print("CONTINUOUS_INCIDENT_STATE=NONE")
        print("ACTIONABLE_ALERT_REQUIRED=NO")
        return 0

    print("CONTINUOUS_INCIDENT_STATE=" + str(incident["current_status"]))
    print("INCIDENT_FINGERPRINT=" + str(incident["incident_fingerprint"]))
    print("INCIDENT_OCCURRENCE_COUNT=" + str(incident["occurrence_count"]))
    print("ACTIONABLE_ALERT_REQUIRED=" + ("YES" if incident["alert_required"] else "NO"))
    print("ALERT_REASON=" + str(incident["alert_reason"]))
    if not incident["alert_required"]:
        print("DUPLICATE_ALERT_SUPPRESSED=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
