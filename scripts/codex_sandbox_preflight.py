from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

from app.services.agent_office.codex_bounded_worker import (
    codex_execution_failure,
    codex_sanitized_environment,
)


def _git_status(root: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _sandbox(
    *,
    mode: str,
    cwd: Path,
    command: list[str],
    source_env: dict[str, str] | None = None,
    timeout: float = 30,
) -> subprocess.CompletedProcess[str]:
    env_source = dict(os.environ if source_env is None else source_env)
    permission_profile = {
        "read-only": ":read-only",
        "workspace-write": ":workspace",
    }[mode]
    return subprocess.run(
        [
            "codex",
            "sandbox",
            "linux",
            "--permissions-profile",
            permission_profile,
            "-C",
            str(cwd),
            *command,
        ],
        cwd=cwd,
        timeout=timeout,
        check=False,
        capture_output=True,
        text=True,
        env=codex_sanitized_environment(env_source),
    )


def _sanitize_diagnostic_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"https?://\S+", "<URL>", value)
    value = re.sub(r"/home/runner/\S+", "<RUNNER_PATH>", value)
    value = re.sub(r"/tmp/\S+", "<TMP_PATH>", value)
    value = re.sub(
        r"(?i)(token|secret|password|credential|api[_-]?key)\s*[:=]\s*\S+",
        r"\1=<REDACTED>",
        value,
    )
    return value[:600]


def _diagnostic_flags(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    text = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    lowered = text.lower()
    terms = {
        "bwrap": "bwrap" in lowered,
        "rtm_newaddr": "rtm_newaddr" in lowered,
        "operation_not_permitted": "operation not permitted" in lowered,
        "panic": "panicked at" in lowered or "thread 'main' panicked" in lowered,
        "user_namespace": "user namespace" in lowered or "userns" in lowered,
        "uid_map": "uid_map" in lowered,
        "setgroups": "setgroups" in lowered,
        "seccomp": "seccomp" in lowered,
        "profile": "permission profile" in lowered or "permissions profile" in lowered,
        "not_found": "no such file or directory" in lowered or "not found" in lowered,
        "invalid_argument": "invalid argument" in lowered or "unexpected argument" in lowered,
    }
    return {
        "stderr_sha256": sha256(text.encode("utf-8")).hexdigest(),
        "stderr_chars": len(text),
        "diagnostic_flags": terms,
        "stderr_excerpt_sanitized": _sanitize_diagnostic_text(text),
    }


class SandboxPreflightFailure(RuntimeError):
    def __init__(
        self,
        evidence: dict[str, Any],
        completed: subprocess.CompletedProcess[str],
    ) -> None:
        super().__init__(str(evidence.get("stderr_class") or "SANDBOX_PREFLIGHT_FAILURE"))
        self.evidence = {**evidence, **_diagnostic_flags(completed)}


def _require_success(
    completed: subprocess.CompletedProcess[str],
    *,
    stage: str,
) -> None:
    failure = codex_execution_failure(
        completed,
        failure_stage=stage,
    )
    if failure is not None:
        raise SandboxPreflightFailure(failure, completed)


def run_preflight(repository_root: Path, output: Path) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    before = _git_status(repository_root)
    evidence: dict[str, Any] = {
        "status": "FAIL",
        "sandbox_backend": "bubblewrap",
        "readonly_preflight": False,
        "workspace_write_preflight": False,
        "network_isolation": False,
        "secret_isolation": False,
        "canonical_worktree_mutation": "NONE",
        "failure_stage": None,
        "exit_code": None,
        "stderr_class": None,
        "retryability": None,
        "stderr_sha256": None,
        "stderr_chars": 0,
        "diagnostic_flags": {},
        "stderr_excerpt_sanitized": None,
    }

    try:
        read_probe = _sandbox(
            mode="read-only",
            cwd=repository_root,
            command=[
                "/bin/sh",
                "-c",
                "test -r README.md && head -n 1 README.md >/dev/null",
            ],
        )
        _require_success(read_probe, stage="sandbox_readonly_read_probe")

        denied_path = repository_root / ".codex-readonly-denied"
        denied_path.unlink(missing_ok=True)
        readonly_write = _sandbox(
            mode="read-only",
            cwd=repository_root,
            command=[
                "/bin/sh",
                "-c",
                ": > .codex-readonly-denied",
            ],
        )
        if readonly_write.returncode == 0 or denied_path.exists():
            raise RuntimeError("read-only sandbox allowed a workspace write")
        evidence["readonly_preflight"] = True

        runner_temp = Path(os.getenv("RUNNER_TEMP") or tempfile.gettempdir())
        with tempfile.TemporaryDirectory(
            prefix="br-codex-sandbox-preflight-",
            dir=runner_temp,
        ) as temp_dir:
            workspace = Path(temp_dir)
            write_probe = _sandbox(
                mode="workspace-write",
                cwd=workspace,
                command=[
                    "/bin/sh",
                    "-c",
                    "printf 'workspace-write-ok\\n' > preflight-write.txt",
                ],
            )
            _require_success(write_probe, stage="sandbox_workspace_write_probe")
            marker = workspace / "preflight-write.txt"
            if marker.read_text(encoding="utf-8") != "workspace-write-ok\n":
                raise RuntimeError("workspace-write sandbox did not persist the probe")
            evidence["workspace_write_preflight"] = True

            network_probe = _sandbox(
                mode="workspace-write",
                cwd=workspace,
                command=[
                    "/usr/bin/python3",
                    "-c",
                    (
                        "import os,sys;"
                        "names=set(os.listdir('/sys/class/net'));"
                        "sys.exit(0 if names <= {'lo'} else 23)"
                    ),
                ],
            )
            _require_success(network_probe, stage="sandbox_network_isolation_probe")
            evidence["network_isolation"] = True

            source_env = dict(os.environ)
            source_env["BR_CODEX_PREFLIGHT_SECRET"] = "must-not-enter-codex"
            secret_probe = _sandbox(
                mode="read-only",
                cwd=workspace,
                command=[
                    "/bin/sh",
                    "-c",
                    "test -z \"$BR_CODEX_PREFLIGHT_SECRET\"",
                ],
                source_env=source_env,
            )
            _require_success(secret_probe, stage="sandbox_secret_isolation_probe")
            evidence["secret_isolation"] = True

        after = _git_status(repository_root)
        if after != before:
            evidence["canonical_worktree_mutation"] = "DETECTED"
            raise RuntimeError("sandbox preflight mutated tracked canonical worktree state")

        evidence["status"] = "PASS"
        return evidence
    except SandboxPreflightFailure as exc:
        evidence.update(
            {
                "failure_stage": exc.evidence.get("failure_stage"),
                "exit_code": exc.evidence.get("exit_code"),
                "stderr_class": exc.evidence.get("stderr_class"),
                "retryability": exc.evidence.get("retryability"),
                "stderr_sha256": exc.evidence.get("stderr_sha256"),
                "stderr_chars": exc.evidence.get("stderr_chars"),
                "diagnostic_flags": exc.evidence.get("diagnostic_flags") or {},
                "stderr_excerpt_sanitized": exc.evidence.get("stderr_excerpt_sanitized"),
            }
        )
        raise
    except Exception as exc:
        evidence.update(
            {
                "failure_stage": "preflight_assertion",
                "exit_code": None,
                "stderr_class": type(exc).__name__,
                "retryability": "DETERMINISTIC_NO_RETRY",
            }
        )
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        evidence = run_preflight(args.repository_root, args.output)
    except Exception as exc:
        print("CODEX_SANDBOX_PREFLIGHT=FAIL")
        print(f"CODEX_SANDBOX_PREFLIGHT_CLASS={type(exc).__name__}")
        return 1

    print("CODEX_SANDBOX_PREFLIGHT=PASS")
    print("CODEX_SANDBOX_READONLY_PREFLIGHT=PASS")
    print("CODEX_SANDBOX_WORKSPACE_WRITE_PREFLIGHT=PASS")
    print("CODEX_SANDBOX_NETWORK_ISOLATION=PASS")
    print("CODEX_SECRET_ISOLATION=PASS")
    print("CANONICAL_WORKTREE_MUTATION=NONE")
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
