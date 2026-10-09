"""V23 explicitly gated diagnostic entry point.

This runner deliberately contains no Telegram-send, ledger-write, training,
production, or publish code. It reuses the V23 ablation-only return in the
existing single-human clone runtime. It never authorizes that runtime itself.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

ABLAT_ONLY = "BR_OWNER_V23_ABLATION_ONLY"
AUTHORIZE = "BR_OWNER_V23_DIAGNOSTIC_AUTHORIZED"
WORKFLOW = "BR V23 Private Qwen Diagnostic"
PRIVATE_INDEX = (
    "BR_OWNER_TELEGRAM_REFERENCE_ENVELOPE_B64",
    "BR_OWNER_TELEGRAM_REFERENCE_INDEX",
)


def validate_diagnostic_environment(
    environment: Mapping[str, str],
    *,
    repository_root: Path,
) -> Path:
    """Fail before importing model/audio modules on any ambiguous execution."""
    if environment.get(ABLAT_ONLY) != "1" or environment.get(AUTHORIZE) != "1":
        raise RuntimeError("V23_DIAGNOSTIC_EXPLICIT_AUTHORIZATION_REQUIRED")
    if environment.get("GITHUB_ACTIONS") == "true" and environment.get("GITHUB_WORKFLOW") != WORKFLOW:
        raise RuntimeError("V23_DIAGNOSTIC_UNTRUSTED_WORKFLOW")
    if not environment.get("TELEGRAM_BOT_TOKEN", "").strip():
        raise RuntimeError("V23_DIAGNOSTIC_OWNER_REFERENCE_ACCESS_MISSING")
    if not any(environment.get(key, "").strip() for key in PRIVATE_INDEX):
        raise RuntimeError("V23_DIAGNOSTIC_OWNER_REFERENCE_INDEX_MISSING")

    location = environment.get("BR_OWNER_AUDITION_WORKSPACE", "").strip()
    if not location:
        raise RuntimeError("V23_DIAGNOSTIC_PRIVATE_WORKSPACE_REQUIRED")
    workspace = Path(location).expanduser()
    if not workspace.is_absolute() or not workspace.is_dir() or workspace.is_symlink():
        raise RuntimeError("V23_DIAGNOSTIC_PRIVATE_WORKSPACE_INVALID")
    actual = workspace.resolve(strict=True)
    repo = repository_root.resolve(strict=True)
    if actual == repo or repo in actual.parents:
        raise RuntimeError("V23_DIAGNOSTIC_WORKSPACE_INSIDE_REPOSITORY")
    if (actual.stat().st_mode & 0o077) != 0:
        raise RuntimeError("V23_DIAGNOSTIC_WORKSPACE_PERMISSIONS_INSECURE")
    if (actual / "v23-private-ablation.json").exists():
        raise RuntimeError("V23_DIAGNOSTIC_EXISTING_RECEIPT_REFUSE_OVERWRITE")
    if environment.get("GITHUB_ACTIONS") == "true":
        runner_tmp = environment.get("RUNNER_TEMP", "").strip()
        if not runner_tmp or Path(runner_tmp).resolve(strict=True) not in actual.parents:
            raise RuntimeError("V23_DIAGNOSTIC_OUTSIDE_RUNNER_TEMP")
    return actual


def main() -> int:
    validate_diagnostic_environment(os.environ, repository_root=Path.cwd())
    from scripts.owner_voice_single_human_clone import main as existing_clone_main
    outcome = existing_clone_main()
    if outcome != 0:
        raise RuntimeError("V23_DIAGNOSTIC_EXECUTION_FAILED")
    print("V23_DIAGNOSTIC_ONLY=PASS")
    print("V23_DIAGNOSTIC_TELEGRAM_DELIVERY=NOT_ATTEMPTED")
    print("V23_DIAGNOSTIC_LEDGER_WRITE=NOT_ATTEMPTED")
    print("V23_DIAGNOSTIC_PRODUCTION=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
