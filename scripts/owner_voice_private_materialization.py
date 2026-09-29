from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from app.services.owner_voice_private_materialization_service import (
    OwnerVoicePrivateMaterializationError,
    materialize_telegram_owner_references,
    parse_owner_reference_index_secret,
    require_private_voice_runtime,
)
from app.services.owner_voice_telegram_handoff_service import (
    parse_reference_envelope_b64,
)


def _env(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    repository_root = Path.cwd().resolve()
    runner_temp = Path(_env("RUNNER_TEMP") or "/tmp").resolve()
    private_root = runner_temp / "br-owner-voice" / "references"
    evidence_root = repository_root / "runtime" / "owner-voice-materialization"

    raw_envelope = _env("BR_OWNER_TELEGRAM_REFERENCE_ENVELOPE_B64")
    raw_index = _env("BR_OWNER_TELEGRAM_REFERENCE_INDEX")
    telegram_token = _env("TELEGRAM_BOT_TOKEN")
    if not raw_envelope and not raw_index:
        raise OwnerVoicePrivateMaterializationError(
            "OWNER_TELEGRAM_REFERENCE_INDEX_NOT_MATERIALIZED"
        )
    if not telegram_token:
        raise OwnerVoicePrivateMaterializationError(
            "TELEGRAM_BOT_TOKEN_NOT_MATERIALIZED"
        )

    if raw_envelope:
        decoded = parse_reference_envelope_b64(raw_envelope)
        index = parse_owner_reference_index_secret(
            json.dumps(decoded, ensure_ascii=False, sort_keys=True)
        )
    else:
        index = parse_owner_reference_index_secret(raw_index)
    print(f"OWNER_TELEGRAM_REFERENCES_FOUND={index['reference_count']}")
    print(f"OWNER_REFERENCE_INDEX_SHA256={index['index_sha256']}")
    print("MEDIA_BYTES_ON_A15=NO")

    result = materialize_telegram_owner_references(
        index,
        private_root=private_root,
        repository_root=repository_root,
        telegram_bot_token=telegram_token,
    )
    _write_json(
        evidence_root / "reference-download-proof.json",
        result["public_evidence"],
    )
    print(
        "OWNER_REFERENCE_DOWNLOAD=PASS "
        f"COUNT={result['materialized_reference_count']}"
    )
    print("RAW_OWNER_AUDIO_PUBLIC_ARTIFACT=0")

    runtime_url = _env("BR_VOICE_RUNTIME_URL")
    runtime_token = _env("BR_VOICE_RUNTIME_TOKEN")
    try:
        root = require_private_voice_runtime(
            base_url=runtime_url,
            auth_token=runtime_token,
        )
    except OwnerVoicePrivateMaterializationError:
        _write_json(
            evidence_root / "runtime-blocker.json",
            {
                "schema": "OwnerVoiceRuntimeBlocker/v1",
                "voice_identity_id": "BR_OWNER_V1",
                "status": "BLOCKED",
                "failure_class": "VOICE_PRIVATE_RUNTIME_NOT_CONFIGURED",
                "downloaded_reference_count": result["materialized_reference_count"],
                "reference_index_sha256": index["index_sha256"],
                "raw_audio_public": False,
                "voice_prompt_created": False,
                "owner_voice_profile_ready": False,
            },
        )
        print("BR_VOICE_RUNTIME_CONFIGURED=false")
        raise
    print("BR_VOICE_RUNTIME_CONFIGURED=true")
    print(f"BR_VOICE_RUNTIME_SCHEME={'HTTPS' if root.startswith('https://') else 'LOOPBACK'}")

    # Prompt preparation is deliberately delegated to the isolated private
    # runtime. This client never invents a generic speaker when the runtime is
    # unavailable or unprepared.
    _write_json(
        evidence_root / "runtime-ready.json",
        {
            "schema": "OwnerVoiceRuntimeReadiness/v1",
            "voice_identity_id": "BR_OWNER_V1",
            "status": "READY_FOR_PRIVATE_PROMPT_PREPARATION",
            "reference_count": result["materialized_reference_count"],
            "reference_index_sha256": index["index_sha256"],
            "runtime_scheme": "HTTPS" if root.startswith("https://") else "LOOPBACK",
            "raw_audio_public": False,
            "generic_voice_fallback": False,
        },
    )
    print("OWNER_VOICE_PRIVATE_MATERIALIZATION=READY_FOR_PROMPT_PREPARATION")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OwnerVoicePrivateMaterializationError as exc:
        # The typed class is safe; exception details are intentionally omitted
        # because provider/transport diagnostics may contain sensitive values.
        print(
            "OWNER_VOICE_PRIVATE_MATERIALIZATION=FAIL "
            f"FAILURE_CLASS={str(exc).split(':', 1)[0]}",
            file=sys.stderr,
        )
        raise SystemExit(31)
