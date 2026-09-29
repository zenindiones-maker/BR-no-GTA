from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


CODE_REVISION = "3428dfd95309a7f3c84fd93259ded0f810d1ff91"
MODEL_REVISION = "fdaf4090a61cb315c138a1faee287ffd6c716309"


def _runtime_root() -> Path:
    configured = os.environ.get("PERSONAPLEX_RUNTIME_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".local/share/br-no-gta/personaplex").resolve()


def _gpu_probe() -> tuple[str, int] | None:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    first = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    if not first or "," not in first:
        return None
    name, memory = first.rsplit(",", 1)
    try:
        return name.strip(), int(memory.strip())
    except ValueError:
        return None


def main() -> int:
    root = _runtime_root()
    receipt_path = root / "install-receipt.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("PERSONAPLEX_PREFLIGHT=BLOCKED INSTALL_RECEIPT_MISSING")
        return 21

    if receipt.get("code_revision") != CODE_REVISION:
        print("PERSONAPLEX_PREFLIGHT=BLOCKED CODE_REVISION_MISMATCH")
        return 22

    if not str(os.environ.get("HF_TOKEN") or "").strip():
        print("PERSONAPLEX_PREFLIGHT=BLOCKED HF_TOKEN_NOT_MATERIALIZED")
        return 23
    print("PERSONAPLEX_HF_TOKEN_PRESENT=true")

    gpu = _gpu_probe()
    if gpu is None:
        print("PERSONAPLEX_PREFLIGHT=BLOCKED NVIDIA_GPU_UNAVAILABLE")
        return 24
    gpu_name, memory_mib = gpu
    print("PERSONAPLEX_GPU_PRESENT=true")
    print(f"PERSONAPLEX_GPU_MEMORY_MIB={memory_mib}")
    print("PERSONAPLEX_GPU_PROFILE=" + gpu_name.replace("\n", " ").replace("\r", " "))

    print("PERSONAPLEX_CODE_REVISION=" + CODE_REVISION)
    print("PERSONAPLEX_MODEL_REVISION=" + MODEL_REVISION)
    print("PERSONAPLEX_LANGUAGE=en")
    print("PERSONAPLEX_PTBR_ELIGIBLE=false")
    print("PERSONAPLEX_PRODUCTION_ELIGIBLE=false")
    print("PERSONAPLEX_LIVE_GPU_PROFILE_REQUIRES_VALIDATION=true")
    print("PERSONAPLEX_PREFLIGHT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
