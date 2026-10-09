"""Strict, light Codespace setup for BR-no-GTA V23.

Default Codespaces image retained intentionally (no devcontainer rebuild).
Never downloads Qwen weights, reads private samples, writes ledger, sends Telegram
or runs background workloads. Creates only an external, local Python venv and
a sanitized local diagnostic receipt. Does not switch/fetch/reset git refs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import venv

EXPECTED_CODESPACE = "br-v23-recovery-gxp67g5g7wphwxjw"
EXPECTED_BRANCH = "work/br-v23-actions-contract-recovery-v1"
EXPECTED_REPOSITORY = "zenindiones-maker/BR-no-GTA"
MIN_FREE_BYTES = 2 * 1024**3
_REMOTE = re.compile(
    r"^(?:https://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"zenindiones-maker/BR-no-GTA(?:\.git)?/?$", re.I,
)
TEST_PATTERNS = (
    "test_owner_voice_*v23_stdlib.py",
    "test_owner_voice_v23_manual_runner_stdlib.py",
    "test_br_v23_codespace_bootstrap_stdlib.py",
)


def validate_identity(env: dict[str, str], *, branch: str, remote: str) -> None:
    if env.get("CODESPACES", "").lower() != "true":
        raise RuntimeError("V23_CODESPACE_REQUIRED_NO_A15_EXECUTION")
    if env.get("CODESPACE_NAME") != EXPECTED_CODESPACE:
        raise RuntimeError("V23_CODESPACE_IDENTITY_MISMATCH")
    if branch != EXPECTED_BRANCH:
        raise RuntimeError("V23_BRANCH_MISMATCH")
    if not _REMOTE.fullmatch(remote.strip()):
        raise RuntimeError("V23_REMOTE_REPOSITORY_MISMATCH")


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True, stderr=subprocess.DEVNULL,
    ).strip()


def _preflight(repo: Path) -> tuple[str, Path]:
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("V23_PYTHON_312_REQUIRED")
    root = Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()
    if root != repo:
        raise RuntimeError("V23_CHECKOUT_ROOT_MISMATCH")
    validate_identity(
        dict(os.environ),
        branch=_git(repo, "branch", "--show-current"),
        remote=_git(repo, "remote", "get-url", "origin"),
    )
    if _git(repo, "status", "--porcelain=v1", "--untracked-files=normal"):
        raise RuntimeError("V23_LOCAL_WIP_PRESENT_NO_AUTOMATIC_MODIFICATION")
    sha = _git(repo, "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("V23_HEAD_INVALID")
    if shutil.disk_usage(Path.home()).free < MIN_FREE_BYTES:
        raise RuntimeError("V23_STORAGE_HEADROOM_BELOW_2GIB")
    return sha, Path.home() / ".cache" / "br-no-gta" / "v23-workstation"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BR V23 Codespace zero-spend-first bootstrap")
    parser.add_argument("--doctor", action="store_true", help="read-only preflight")
    parser.add_argument("--setup", action="store_true", help="local venv + existing unit tests")
    args = parser.parse_args(argv)
    if args.doctor == args.setup:
        parser.error("select exactly one of --doctor or --setup")
    repo = Path(__file__).resolve().parents[2]
    sha, state = _preflight(repo)
    print("BR_CODESPACE_IDENTITY=PASS", flush=True)
    print("BR_V23_HEAD=" + sha, flush=True)
    print("BR_V23_DEFAULT_IMAGE_PRESERVED=TRUE", flush=True)
    print("BR_V23_PRIVATE_AUDIO=NOT_ACCESSED", flush=True)
    if args.doctor:
        print("BR_V23_CODESPACE_DOCTOR=PASS", flush=True)
        return 0

    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    state.chmod(0o700)
    venv_path = state / "venv"
    if not (venv_path / "bin" / "python").exists():
        venv.EnvBuilder(with_pip=True, clear=False, symlinks=True).create(venv_path)
    interpreter = venv_path / "bin" / "python"
    controlled_env = dict(os.environ)
    controlled_env.update({
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(repo),
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
    })
    for name in (
        "TELEGRAM_BOT_TOKEN", "BR_OWNER_TELEGRAM_REFERENCE_ENVELOPE_B64",
        "BR_OWNER_TELEGRAM_REFERENCE_INDEX", "GITHUB_TOKEN", "GH_TOKEN",
    ):
        controlled_env.pop(name, None)
    for pattern in TEST_PATTERNS:
        subprocess.run(
            [str(interpreter), "-m", "unittest", "discover", "-s", "tests",
             "-p", pattern, "-v"],
            cwd=repo, env=controlled_env, check=True,
        )

    receipt = {
        "schema_version": "BRV23CodespaceReadiness/v1",
        "codespace": EXPECTED_CODESPACE,
        "repository": EXPECTED_REPOSITORY,
        "branch": EXPECTED_BRANCH,
        "head": sha,
        "stdlib_contract_patterns": list(TEST_PATTERNS),
        "status": "PASS",
        "private_qwen_inference": "NOT_ATTEMPTED",
        "human_reference_materialized": False,
        "telegram_delivery": "NOT_ATTEMPTED",
        "production_authorized": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    receipts_dir = state / "receipts"
    receipts_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    receipts_dir.chmod(0o700)
    path = receipts_dir / (sha + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    with path.open("x", encoding="utf-8") as f:
        os.fchmod(f.fileno(), 0o600)
        json.dump(receipt, f, sort_keys=True, indent=2)
        f.write("\n")
    print("BR_V23_UNIT_CONTRACTS=PASS")
    print("BR_V23_WORKSTATION_READINESS=PASS")
    print("BR_V23_PRIVATE_QWEN_INFERENCE=NOT_ATTEMPTED")
    print("BR_V23_TELEGRAM_DELIVERY=NOT_ATTEMPTED")
    print("BR_V23_BACKGROUND_JOBS=NONE")
    print("BR_V23_VENV=" + str(venv_path))
    print("BR_V23_RECEIPT=" + str(path))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        # Do not emit path-sensitive exception strings or remote credentials.
        if isinstance(exc, RuntimeError):
            print("BR_V23_WORKSTATION_BLOCKED=" + str(exc).split(":")[0], file=sys.stderr)
        else:
            print("BR_V23_WORKSTATION_BLOCKED=LOCAL_SETUP_OR_TEST_FAILURE", file=sys.stderr)
        raise SystemExit(1)
