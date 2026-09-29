from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from app.database.telegram_user_input_repository import list_recent_telegram_user_inputs
from app.services.owner_voice_telegram_handoff_service import (
    build_owner_voice_reference_index,
    handoff_dispatch_key,
    handoff_reference_index_to_actions,
    redacted_reference_index_summary,
)
from app.services.telegram_ingress_policy_service import configured_allowed_chat_ids


DEFAULT_REPOSITORY = "zenindiones-maker/BR-no-GTA"
DEFAULT_LIMIT = 500


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _owner_user_id(state: dict[str, Any]) -> int:
    raw = str(os.environ.get("TELEGRAM_ALLOWED_USER_ID") or "").strip()
    if not raw:
        raw = str(state.get("allowed_user_id") or "").strip()
    if not raw:
        raise RuntimeError("OWNER_TELEGRAM_AUTHORITY_UNAVAILABLE")
    return int(raw)


def _state_file() -> Path:
    configured = str(os.environ.get("BR_OWNER_VOICE_HANDOFF_STATE_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local/state/br-no-gta/owner-voice-reference-handoff.json"


def main() -> int:
    control_state_path = Path(
        os.environ.get(
            "TELEGRAM_CONTROL_STATE_FILE",
            str(Path.home() / ".local/state/br-no-gta/telegram-control.json"),
        )
    )
    control_state = _load_json(control_state_path)
    owner_user_id = _owner_user_id(control_state)
    allowed_chat_ids = configured_allowed_chat_ids(control_state)
    if not allowed_chat_ids:
        raise RuntimeError("OWNER_TELEGRAM_AUTHORIZED_CHAT_UNAVAILABLE")

    records = list_recent_telegram_user_inputs(limit=DEFAULT_LIMIT)
    index = build_owner_voice_reference_index(
        records=records,
        owner_user_id=owner_user_id,
        allowed_chat_ids=allowed_chat_ids,
    )
    summary = redacted_reference_index_summary(index)
    print(f"OWNER_TELEGRAM_REFERENCES_FOUND={summary['reference_count']}", flush=True)
    print(f"OWNER_TELEGRAM_REFERENCE_INDEX_SHA256={summary['index_sha256']}", flush=True)
    print("MEDIA_BYTES_ON_A15=NO", flush=True)

    if summary["reference_count"] <= 0:
        print("OWNER_VOICE_REFERENCE_HANDOFF=OWNER_TELEGRAM_REFERENCE_DISCOVERY_EMPTY", flush=True)
        return 3

    repository = (
        str(os.environ.get("BR_GITHUB_REPOSITORY") or "").strip()
        or DEFAULT_REPOSITORY
    )
    branch = str(os.environ.get("BR_GITHUB_BRANCH") or "").strip()
    if not branch:
        branch = _git_value("branch", "--show-current")
    head = _git_value("rev-parse", "HEAD")
    dispatch_key = handoff_dispatch_key(summary["index_sha256"])

    handoff_state_path = _state_file()
    previous = _load_json(handoff_state_path)
    if previous.get("dispatch_key") == dispatch_key:
        print("OWNER_VOICE_REFERENCE_HANDOFF=UNCHANGED", flush=True)
        return 0

    receipt = handoff_reference_index_to_actions(
        index,
        repository=repository,
        branch=branch,
    )

    handoff_state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = handoff_state_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "schema": "OwnerVoiceReferenceHandoffState/v1",
                "dispatch_key": dispatch_key,
                "repository": repository,
                "branch": branch,
                "head_sha": head,
                "index_sha256": summary["index_sha256"],
                "reference_count": summary["reference_count"],
                "status": receipt["status"],
                "sensitive_metadata_recorded": False,
                "media_bytes_on_a15": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(handoff_state_path)
    try:
        handoff_state_path.chmod(0o600)
    except OSError:
        pass

    print("OWNER_VOICE_REFERENCE_HANDOFF=DISPATCHED", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Deliberately do not interpolate exception bodies: subprocess failures
        # can contain provider diagnostics. The gateway log keeps only the typed
        # failure class.
        print(
            "OWNER_VOICE_REFERENCE_HANDOFF=FAIL "
            + f"FAILURE_CLASS={type(exc).__name__}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(2)
