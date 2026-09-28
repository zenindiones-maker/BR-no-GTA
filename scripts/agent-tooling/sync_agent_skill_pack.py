#!/usr/bin/env python3
"""Materialize manifest-approved skill bundles from exact upstream commits."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config" / "agent_skill_pack_v1.json"


def _run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def _assert_cloud_environment() -> None:
    prefix = os.environ.get("PREFIX", "")
    if os.environ.get("TERMUX_VERSION") or "com.termux" in prefix:
        raise RuntimeError("agent skill materialization is forbidden in Termux")


def skill_tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        (item for item in path.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(path).as_posix(),
    )
    if not files:
        raise RuntimeError(f"empty skill bundle: {path}")
    for item in files:
        relative = item.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def checkout_revision(repository: str, commit: str, destination: Path) -> Path:
    url = f"https://github.com/{repository}.git"
    if not (destination / ".git").is_dir():
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run("git", "clone", "--no-checkout", url, str(destination))
    _run("git", "fetch", "origin", commit, cwd=destination)
    _run("git", "checkout", "--detach", commit, cwd=destination)
    if _run("git", "rev-parse", "HEAD", cwd=destination) != commit:
        raise RuntimeError(f"source checkout pin mismatch for {repository}")
    if _run("git", "status", "--porcelain", cwd=destination):
        raise RuntimeError(f"source checkout is dirty for {repository}")
    return destination


def sync_skill(
    source_repo: str,
    source_commit: str,
    source_path: str,
    destination: Path,
    *,
    tooling_root: Path,
) -> str:
    checkout = tooling_root / (source_repo.replace("/", "-") + "-" + source_commit)
    source_root = checkout_revision(source_repo, source_commit, checkout)
    source = source_root / source_path
    if not source.is_dir():
        raise RuntimeError(f"approved source path is missing: {source_repo}:{source_path}")
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    return skill_tree_digest(destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill", action="append", default=[])
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--verify-upstream", action="store_true")
    args = parser.parse_args()

    _assert_cloud_environment()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    selected = set(args.skill)
    tooling_root = Path(
        os.environ.get(
            "BR_AGENT_TOOLING_ROOT",
            str(Path.home() / ".local" / "share" / "br-agent-tooling"),
        )
    ).expanduser()

    results = {}
    for entry in manifest["skills"]:
        local_path = entry.get("local_path")
        if not local_path:
            continue
        skill_id = entry["skill_id"]
        if selected and skill_id not in selected:
            continue
        destination = ROOT / local_path
        source = entry["source"]
        if args.verify_upstream:
            if not destination.is_dir():
                raise RuntimeError(f"materialized skill is missing: {skill_id}")
            expected = entry.get("content_digest")
            if not expected:
                raise RuntimeError(
                    f"missing manifest digest for pinned upstream verification: {skill_id}"
                )
            local_digest = skill_tree_digest(destination)
            checkout = tooling_root / (
                source["repository"].replace("/", "-") + "-" + source["commit"]
            )
            source_root = checkout_revision(
                source["repository"],
                source["commit"],
                checkout,
            )
            upstream_path = source_root / source["path"]
            if not upstream_path.is_dir():
                raise RuntimeError(
                    f"approved upstream path is missing: {skill_id}"
                )
            upstream_digest = skill_tree_digest(upstream_path)
            if local_digest != expected:
                raise RuntimeError(
                    f"local digest mismatch for {skill_id}: "
                    f"expected={expected} actual={local_digest}"
                )
            if upstream_digest != expected:
                raise RuntimeError(
                    f"upstream digest mismatch for {skill_id}: "
                    f"expected={expected} actual={upstream_digest}"
                )
            actual = local_digest
        elif args.check_only:
            actual = skill_tree_digest(destination)
        else:
            actual = sync_skill(
                source["repository"],
                source["commit"],
                source["path"],
                destination,
                tooling_root=tooling_root,
            )
        expected = entry.get("content_digest")
        if expected and actual != expected:
            raise RuntimeError(
                f"digest mismatch for {skill_id}: expected={expected} actual={actual}"
            )
        results[skill_id] = actual

    print(json.dumps(results, indent=2, sort_keys=True))
    print("AGENT_SKILL_PACK_MATERIALIZATION=PASS")
    if args.verify_upstream:
        print("PINNED_UPSTREAM_CONTENT_VERIFIED=PASS")


if __name__ == "__main__":
    main()
