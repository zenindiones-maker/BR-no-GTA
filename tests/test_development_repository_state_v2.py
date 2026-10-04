from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from app.services.development_repository_state_service import (
    DevelopmentLocalOnlyProgressError,
    inspect_development_repository_state,
)


def run(cwd: Path, *args: str) -> str:
    return subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True).stdout.strip()


def init_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    run(repo, "git", "config", "user.email", "test@example.invalid")
    run(repo, "git", "config", "user.name", "Test")
    (repo / "app").mkdir()
    (repo / "app" / "base.py").write_text("BASE = 1\n")
    run(repo, "git", "add", "app/base.py")
    run(repo, "git", "commit", "-m", "base")
    run(repo, "git", "branch", "-M", "work/gate6f-analytics-learning")
    run(repo, "git", "remote", "add", "origin", str(remote))
    run(repo, "git", "push", "-u", "origin", "work/gate6f-analytics-learning")
    return repo, remote


def test_detects_local_only_commit_even_when_worktree_is_clean(tmp_path: Path):
    repo, _ = init_repo(tmp_path)
    (repo / "app" / "base.py").write_text("BASE = 2\n")
    run(repo, "git", "add", "app/base.py")
    run(repo, "git", "commit", "-m", "local only")

    state = inspect_development_repository_state(repo, refresh_remote=True)
    assert state.worktree_dirty is False
    assert state.local_only_progress_detected is True
    assert state.local_only_commits
    assert state.local_only_commits[0].sha == run(repo, "git", "rev-parse", "HEAD")
    with pytest.raises(DevelopmentLocalOnlyProgressError):
        state.assert_terminal_durability()


def test_remote_recovery_representation_clears_local_only_commit(tmp_path: Path):
    repo, _ = init_repo(tmp_path)
    (repo / "app" / "base.py").write_text("BASE = 2\n")
    run(repo, "git", "add", "app/base.py")
    run(repo, "git", "commit", "-m", "wip")
    head = run(repo, "git", "rev-parse", "HEAD")
    run(repo, "git", "push", "origin", f"{head}:refs/heads/recovery/dev/m1")
    state = inspect_development_repository_state(repo, refresh_remote=True)
    assert state.local_only_progress_detected is False
    state.assert_terminal_durability()


def test_inventory_classifies_untracked_state_without_exposing_content(tmp_path: Path):
    repo, _ = init_repo(tmp_path)
    (repo / "config.yaml").write_text("runtime: local\n")
    (repo / ".env").write_text("TOKEN=do-not-print\n")
    (repo / "app" / "new.py").write_text("X = 1\n")
    (repo / "artifacts").mkdir()
    (repo / "artifacts" / "proof.zip").write_bytes(b"not really zip")

    state = inspect_development_repository_state(repo, refresh_remote=False)
    by_path = {item.path: item for item in state.inventory}
    assert by_path["config.yaml"].classification == "LOCAL_RUNTIME_CONFIG"
    assert by_path[".env"].classification == "PRIVATE_SECRET"
    assert by_path["app/new.py"].classification == "RECOVERABLE_SOURCE"
    assert by_path["artifacts/proof.zip"].classification == "LARGE_EVIDENCE"
    assert all("do-not-print" not in item.redacted_summary for item in state.inventory)
    assert by_path["config.yaml"].recommended_destination == "~/.config/br-no-gta/config.yaml"
