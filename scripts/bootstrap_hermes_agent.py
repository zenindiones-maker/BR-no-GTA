from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time


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




_TRANSIENT_GIT_FETCH_MARKERS = (
    "rpc failed",
    "remote end hung up unexpectedly",
    "early eof",
    "connection reset",
    "connection timed out",
    "could not resolve host",
    "temporary failure in name resolution",
    "tls",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
    "the requested url returned error: 429",
    "the requested url returned error: 500",
    "the requested url returned error: 502",
    "the requested url returned error: 503",
    "the requested url returned error: 504",
)


def _fetch_pinned_commit(target: Path, expected_sha: str) -> None:
    attempts = 2
    for attempt in range(1, attempts + 1):
        try:
            _run("git", "fetch", "--depth=1", "origin", expected_sha, cwd=target)
            return
        except subprocess.CalledProcessError as exc:
            stderr = str(exc.stderr or "").strip()
            normalized = stderr.casefold()
            transient = any(
                marker in normalized
                for marker in _TRANSIENT_GIT_FETCH_MARKERS
            )
            if not transient or attempt >= attempts:
                detail = stderr[-1200:] if stderr else "no git stderr captured"
                raise RuntimeError(
                    "HERMES_UPSTREAM_FETCH_FAILED:"
                    f"attempt={attempt}:transient={str(transient).upper()}:"
                    + detail
                ) from exc
            time.sleep(2.0)

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
                "/gateway/",
                "/plugins/",
                "/providers/",
                "/*.py",
                "/LICENSE",
                "/pyproject.toml",
            ]) + "\n",
            encoding="utf-8",
        )
        _fetch_pinned_commit(target, expected_sha)
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
