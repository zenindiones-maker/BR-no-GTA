from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Iterable

from app.services.development_continuity_guard_service import (
    InventoryClassification,
    classify_inventory_path,
)


class DevelopmentLocalOnlyProgressError(RuntimeError):
    pass


@dataclass(frozen=True)
class DevelopmentInventoryEntry:
    path: str
    status: str
    tracked: bool
    classification: str
    redacted_summary: str
    recommended_destination: str | None = None


@dataclass(frozen=True)
class LocalOnlyCommit:
    sha: str
    local_refs: tuple[str, ...]


@dataclass(frozen=True)
class DevelopmentRepositoryState:
    worktree_dirty: bool
    inventory: tuple[DevelopmentInventoryEntry, ...]
    local_only_progress_detected: bool
    local_only_commits: tuple[LocalOnlyCommit, ...]
    remote_observation_status: str

    def assert_terminal_durability(self) -> None:
        if self.remote_observation_status != "VERIFIED":
            raise DevelopmentLocalOnlyProgressError(
                "DEVELOPMENT_DURABILITY_BLOCKED: remote refs not verified"
            )
        if self.local_only_progress_detected:
            raise DevelopmentLocalOnlyProgressError(
                "DEVELOPMENT_DURABILITY_BLOCKED: LOCAL_ONLY_PROGRESS_DETECTED"
            )
        material = tuple(
            item
            for item in self.inventory
            if item.classification
            != InventoryClassification.EPHEMERAL_GENERATED.value
        )
        if material:
            raise DevelopmentLocalOnlyProgressError(
                "DEVELOPMENT_DURABILITY_BLOCKED: material working state is not clean"
            )


def _run(
    repo: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    cp = subprocess.run(
        [*args],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if check and cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or b"").decode(
            "utf-8", errors="replace"
        ).strip()
        raise RuntimeError(
            f"command failed ({cp.returncode}): {' '.join(args)}: {detail[:800]}"
        )
    return cp


def _text(repo: Path, *args: str, check: bool = True) -> str:
    return _run(repo, *args, check=check).stdout.decode(
        "utf-8", errors="replace"
    ).strip()


def _inventory(repo: Path) -> tuple[DevelopmentInventoryEntry, ...]:
    raw = _run(
        repo,
        "git",
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ).stdout
    fields = raw.split(b"\0")
    entries: list[DevelopmentInventoryEntry] = []
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        decoded = field.decode("utf-8", errors="surrogateescape")
        if len(decoded) < 4:
            continue
        status = decoded[:2]
        path = decoded[3:]
        tracked = status != "??"
        classification = classify_inventory_path(
            path,
            tracked=tracked,
        ).value
        destination = None
        if classification == InventoryClassification.LOCAL_RUNTIME_CONFIG.value:
            destination = f"~/.config/br-no-gta/{Path(path).name}"
        summary = (
            f"classification={classification}; status={status}; "
            "content=REDACTED"
        )
        entries.append(
            DevelopmentInventoryEntry(
                path=path,
                status=status,
                tracked=tracked,
                classification=classification,
                redacted_summary=summary,
                recommended_destination=destination,
            )
        )
        if ("R" in status or "C" in status) and index < len(fields):
            # porcelain v1 -z emits the original path as a second NUL field.
            index += 1
    ignored = _run(
        repo,
        "git",
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
        check=False,
    ).stdout
    known_paths = {item.path for item in entries}
    for raw_path in ignored.split(b"\0"):
        if not raw_path:
            continue
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if path in known_paths:
            continue
        classification = classify_inventory_path(path, tracked=False).value
        if classification not in {
            InventoryClassification.PRIVATE_SECRET.value,
            InventoryClassification.LOCAL_RUNTIME_CONFIG.value,
        }:
            continue
        destination = None
        if classification == InventoryClassification.LOCAL_RUNTIME_CONFIG.value:
            destination = f"~/.config/br-no-gta/{Path(path).name}"
        entries.append(
            DevelopmentInventoryEntry(
                path=path,
                status="!!",
                tracked=False,
                classification=classification,
                redacted_summary=(
                    f"classification={classification}; status=!!; "
                    "content=REDACTED"
                ),
                recommended_destination=destination,
            )
        )
    return tuple(sorted(entries, key=lambda item: item.path))


def _remote_head_oids(repo: Path) -> tuple[str, ...]:
    refs = _text(
        repo,
        "git",
        "for-each-ref",
        "--format=%(objectname)",
        "refs/remotes/origin",
        check=False,
    )
    values = {
        line.strip()
        for line in refs.splitlines()
        if len(line.strip()) == 40
    }
    return tuple(sorted(values))


def _local_branch_refs(repo: Path) -> tuple[tuple[str, str], ...]:
    raw = _text(
        repo,
        "git",
        "for-each-ref",
        "--format=%(refname) %(objectname)",
        "refs/heads",
        check=False,
    )
    refs: list[tuple[str, str]] = []
    for line in raw.splitlines():
        parts = line.strip().split()
        if len(parts) != 2 or len(parts[1]) != 40:
            continue
        refs.append((parts[0], parts[1]))
    head = _text(repo, "git", "rev-parse", "HEAD", check=False)
    if len(head) == 40:
        refs.append(("HEAD", head))
    return tuple(refs)


def _local_only_commits(
    repo: Path,
    remote_oids: Iterable[str],
) -> tuple[LocalOnlyCommit, ...]:
    remote = tuple(dict.fromkeys(remote_oids))
    observed: dict[str, set[str]] = {}
    for ref, oid in _local_branch_refs(repo):
        args = ["git", "rev-list", "--max-count=512", oid]
        if remote:
            args.extend(["--not", *remote])
        raw = _text(repo, *args, check=False)
        for sha in raw.splitlines():
            sha = sha.strip()
            if len(sha) == 40:
                observed.setdefault(sha, set()).add(ref)
    return tuple(
        LocalOnlyCommit(
            sha=sha,
            local_refs=tuple(sorted(refs)),
        )
        for sha, refs in sorted(observed.items())
    )


def inspect_development_repository_state(
    repo_root: Path | str,
    *,
    refresh_remote: bool,
) -> DevelopmentRepositoryState:
    repo = Path(repo_root).resolve()
    if not _text(repo, "git", "rev-parse", "--git-dir", check=False):
        raise ValueError("repo_root must be a git worktree")

    remote_status = "CACHED"
    if refresh_remote:
        fetch = _run(
            repo,
            "git",
            "fetch",
            "--prune",
            "origin",
            "+refs/heads/*:refs/remotes/origin/*",
            check=False,
        )
        remote_status = "VERIFIED" if fetch.returncode == 0 else "FAILED"

    remote_oids = _remote_head_oids(repo)
    if not remote_oids and remote_status != "FAILED":
        remote_status = "NO_REMOTE_REFS"
    inventory = _inventory(repo)
    local_only = _local_only_commits(repo, remote_oids)
    return DevelopmentRepositoryState(
        worktree_dirty=bool(inventory),
        inventory=inventory,
        local_only_progress_detected=bool(local_only),
        local_only_commits=local_only,
        remote_observation_status=remote_status,
    )
