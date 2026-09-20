from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "integrations" / "hermes_agent" / "UPSTREAM.lock"


def _run(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        list(args),
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def bootstrap(target: Path) -> dict:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    repository = str(lock["repository"])
    expected_sha = str(lock["commit"]).lower()
    expected_license = str(lock["license"])

    if target.exists():
        observed = ""
        try:
            observed = _run("git", "rev-parse", "HEAD", cwd=target).lower()
        except Exception:
            observed = ""
        if observed != expected_sha:
            shutil.rmtree(target)

    if not target.exists():
        target.mkdir(parents=True)
        _run("git", "init", cwd=target)
        _run("git", "remote", "add", "origin", repository, cwd=target)
        _run("git", "sparse-checkout", "init", "--no-cone", cwd=target)
        sparse = target / ".git" / "info" / "sparse-checkout"
        sparse.write_text(
            "\n".join([
                "/hermes_cli/",
                "/tools/",
                "/agent/",
                "/plugins/",
                "/providers/",
                "/*.py",
                "/LICENSE",
                "/pyproject.toml",
            ]) + "\n",
            encoding="utf-8",
        )
        _run("git", "fetch", "--depth=1", "origin", expected_sha, cwd=target)
        _run("git", "checkout", "--detach", "FETCH_HEAD", cwd=target)

    observed_sha = _run("git", "rev-parse", "HEAD", cwd=target).lower()
    if observed_sha != expected_sha:
        raise RuntimeError(f"Hermes upstream SHA mismatch: {observed_sha} != {expected_sha}")
    if _run("git", "status", "--porcelain", cwd=target):
        raise RuntimeError("Hermes upstream bootstrap produced a dirty checkout")

    license_text = (target / "LICENSE").read_text(encoding="utf-8")
    if expected_license != "MIT" or not license_text.startswith("MIT License"):
        raise RuntimeError("Hermes core license verification failed")

    pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
    if 'license = "MIT"' not in pyproject:
        raise RuntimeError("Hermes pyproject license metadata is not MIT")
    if f'version = "{lock["version"]}"' not in pyproject:
        raise RuntimeError("Hermes upstream version mismatch")

    return {
        "status": "PASS",
        "repository": repository,
        "sha": observed_sha,
        "version": lock["version"],
        "license": "MIT",
        "sparse_checkout": True,
        "vendored_into_br_repo": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = bootstrap(args.target)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print("HERMES_UPSTREAM_SHA=" + result["sha"])
    print("HERMES_CORE_LICENSE=MIT")
    print("HERMES_UPSTREAM_PINNED=PASS")
    print("HERMES_LICENSE_AUDIT=PASS")
    print("HERMES_RUNTIME_BOOTSTRAP=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
