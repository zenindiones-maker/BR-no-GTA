from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
from typing import Any, Iterable, Sequence


_ALLOWED_GATE_TOOLS = {"python", "pytest", "git"}
_FORBIDDEN_GIT_SUBCOMMANDS = {"push", "pull", "fetch", "merge", "rebase", "remote"}


@dataclass(frozen=True)
class IntegrationGateResult:
    status: str
    base_sha: str
    candidate_commit_sha: str
    files_changed: tuple[str, ...]
    conflicts_detected: tuple[str, ...]
    tests_run: tuple[dict[str, Any], ...]
    quality_checks: dict[str, Any]
    performance_checks: dict[str, Any]
    security_checks: dict[str, Any]
    integration_candidate: bool
    canonical_push_authority: str
    duration_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _path_allowed(path: str, allowed_paths: Sequence[str]) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    return any(
        normalized == allowed.strip("/")
        or normalized.startswith(f"{allowed.strip('/')}/")
        for allowed in allowed_paths
        if allowed.strip("/")
    )


def _validate_command(command: Sequence[str]) -> None:
    if not command:
        raise ValueError("integration gate command must not be empty")
    tool = Path(command[0]).name
    if tool not in _ALLOWED_GATE_TOOLS:
        raise PermissionError(f"integration gate tool is not allowlisted: {tool}")
    if tool == "git" and len(command) > 1 and command[1] in _FORBIDDEN_GIT_SUBCOMMANDS:
        raise PermissionError("integration gate may not mutate or contact a remote")


def changed_paths(repository_root: Path, base_sha: str, candidate_sha: str) -> tuple[str, ...]:
    completed = _git(
        repository_root,
        "diff",
        "--name-only",
        f"{base_sha}..{candidate_sha}",
        "--",
    )
    return tuple(sorted(filter(None, completed.stdout.splitlines())))


def detect_candidate_conflicts(
    write_sets: dict[str, Sequence[str]],
) -> tuple[str, ...]:
    conflicts: set[str] = set()
    identities = sorted(write_sets)
    for index, left in enumerate(identities):
        for right in identities[index + 1:]:
            for a in write_sets[left]:
                aa = a.replace("\\", "/").rstrip("/")
                for b in write_sets[right]:
                    bb = b.replace("\\", "/").rstrip("/")
                    if aa == bb or aa.startswith(f"{bb}/") or bb.startswith(f"{aa}/"):
                        conflicts.add(f"{left}<->{right}:{aa if len(aa) <= len(bb) else bb}")
    return tuple(sorted(conflicts))


def run_integration_gate(
    *,
    repository_root: str | Path,
    base_sha: str,
    candidate_commit_sha: str,
    allowed_paths: Sequence[str],
    focused_test_commands: Iterable[Sequence[str]] = (),
    contract_test_commands: Iterable[Sequence[str]] = (),
    quality_checks: dict[str, Any] | None = None,
    performance_checks: dict[str, Any] | None = None,
    conflicts_detected: Sequence[str] = (),
) -> IntegrationGateResult:
    root = Path(repository_root).resolve()
    started = time.perf_counter()
    ancestor = _git(
        root,
        "merge-base",
        "--is-ancestor",
        base_sha,
        candidate_commit_sha,
        check=False,
    )
    if ancestor.returncode != 0:
        raise PermissionError("candidate commit is not descended from authorized base SHA")
    files = changed_paths(root, base_sha, candidate_commit_sha)
    if not files:
        raise ValueError("candidate commit has no changed files")
    outside = tuple(path for path in files if not _path_allowed(path, allowed_paths))
    if outside:
        raise PermissionError(f"candidate changes paths outside lease: {outside}")
    conflicts = tuple(sorted(set(str(item) for item in conflicts_detected if str(item).strip())))
    tests: list[dict[str, Any]] = []
    security = {
        "base_sha_ancestry": "PASS",
        "allowed_paths": "PASS",
        "remote_mutation": "FORBIDDEN",
        "canonical_push_authority": "NONE",
        "path_conflicts": "PASS" if not conflicts else "FAIL",
    }
    with tempfile.TemporaryDirectory(prefix="br-integration-gate-") as temp_dir:
        workspace = Path(temp_dir) / "candidate"
        add = _git(root, "worktree", "add", "--detach", str(workspace), candidate_commit_sha, check=False)
        if add.returncode != 0:
            raise RuntimeError("integration gate could not create candidate worktree")
        try:
            for category, commands in (
                ("focused", tuple(focused_test_commands)),
                ("contract", tuple(contract_test_commands)),
            ):
                for command in commands:
                    normalized = tuple(str(item) for item in command)
                    _validate_command(normalized)
                    completed = subprocess.run(
                        list(normalized),
                        cwd=workspace,
                        capture_output=True,
                        text=True,
                        timeout=900,
                        check=False,
                    )
                    tests.append(
                        {
                            "category": category,
                            "command": shlex.join(normalized),
                            "status": "PASS" if completed.returncode == 0 else "FAIL",
                            "exit_code": completed.returncode,
                            "stdout_tail": completed.stdout[-2000:],
                            "stderr_tail": completed.stderr[-2000:],
                        }
                    )
        finally:
            _git(root, "worktree", "remove", "--force", str(workspace), check=False)

    quality = dict(quality_checks or {})
    performance = dict(performance_checks or {})
    tests_pass = all(item["status"] == "PASS" for item in tests)
    quality_pass = all(value not in {False, "FAIL"} for value in quality.values())
    performance_pass = all(value not in {False, "FAIL"} for value in performance.values())
    passed = tests_pass and quality_pass and performance_pass and not conflicts
    return IntegrationGateResult(
        status="PASS" if passed else "FAIL",
        base_sha=base_sha,
        candidate_commit_sha=candidate_commit_sha,
        files_changed=files,
        conflicts_detected=conflicts,
        tests_run=tuple(tests),
        quality_checks=quality,
        performance_checks=performance,
        security_checks=security,
        integration_candidate=passed,
        canonical_push_authority="NONE",
        duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
    )


def write_integration_artifact(result: IntegrationGateResult, path: str | Path) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        result.to_dict(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    target.write_text(payload, encoding="utf-8")
    return str(target)
