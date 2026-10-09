"""Read-only, full tracked-tree source inventory for BR V23.

Evidence scope is STATIC_SOURCE only. Does NOT run REA6/Ghidra, import project
modules, load owner audio, read binary/media payload, send data, or grant
security/runtime/production approval. All counts are per exact git HEAD.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys

SCHEMA = "BRV23RepositorySourceInventory/v1"
PYTHON = {".py"}
JAVASCRIPT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
NATIVE_SOURCE = {".c", ".cc", ".cpp", ".h", ".hpp", ".rs", ".go", ".java", ".cs"}
NATIVE_BINARY = {".so", ".dll", ".dylib", ".exe", ".elf", ".wasm", ".class", ".jar"}
MEDIA = {".wav", ".mp3", ".mp4", ".webm", ".mkv", ".mov", ".flac",
         ".png", ".jpg", ".jpeg", ".webp", ".ogg", ".opus"}
MODEL = {".pt", ".pth", ".safetensors", ".onnx", ".ckpt", ".gguf", ".bin"}
MAX_PYTHON_BYTES = 2 * 1024 * 1024
CRITICAL_REFERENCES = (
    "AGENTS.md",
    "docs/governance/a15-control-plane-only.md",
    "docs/operations/br-v23-codespace-free-quota.md",
    "scripts/workstations/br_v23_codespace_bootstrap.py",
    "scripts/owner_voice_v23_manual_runner.py",
    "app/services/owner_voice_qwen_ablation_v23.py",
    ".github/workflows/br-v23-isolated-contracts.yml",
)


def category(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in PYTHON:
        return "python_source"
    if suffix in JAVASCRIPT:
        return "javascript_source"
    if suffix in NATIVE_SOURCE:
        return "native_managed_source"
    if suffix in NATIVE_BINARY:
        return "native_managed_binary"
    if suffix in MEDIA:
        return "media_asset_metadata_only"
    if suffix in MODEL:
        return "model_weight_metadata_only"
    if path.startswith(".github/workflows/"):
        return "github_workflow"
    if suffix in {".md", ".rst", ".txt", ".html"}:
        return "documentation"
    return "other_tracked"


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL)


def _checked_git_paths(root: Path) -> tuple[str, list[str]]:
    head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    if len(head) != 40 or any(c not in "0123456789abcdef" for c in head):
        raise ValueError("INVALID_HEAD")
    items = _git(root, "ls-files", "-z").split(b"\0")
    items = [item for item in items if item]
    if len(set(items)) != len(items):
        raise ValueError("DUPLICATE_TRACKED_PATH")
    # Surrogate escape retains unusual git names without ignoring files;
    # such names are counted without printing them to public CI logs.
    paths = [os.fsdecode(raw) for raw in items]
    return head, paths


def inventory(root: Path, *, strict_critical: bool = True) -> dict:
    head, paths = _checked_git_paths(root)
    counts = Counter()
    problems = Counter()
    tracked = set(paths)
    for name in paths:
        if (name.startswith("/") or "\x00" in name
                or ".." in PurePosixPath(name).parts):
            problems["untrusted_tracked_path"] += 1
            continue
        kind = category(name)
        counts[kind] += 1
        path = root / name
        try:
            item = path.lstat()
        except OSError:
            problems["tracked_file_missing"] += 1
            continue
        if stat.S_ISLNK(item.st_mode):
            problems["tracked_symlink_not_followed"] += 1
            continue
        if not stat.S_ISREG(item.st_mode):
            problems["tracked_non_regular"] += 1
            continue
        if kind == "python_source":
            if item.st_size > MAX_PYTHON_BYTES:
                problems["python_source_over_limit"] += 1
                continue
            try:
                ast.parse(path.read_bytes(), filename="<tracked-python-source>")
            except (SyntaxError, UnicodeError, ValueError):
                problems["python_ast_parse_error"] += 1
    missing_critical = [name for name in CRITICAL_REFERENCES if name not in tracked]
    if missing_critical:
        problems["critical_reference_missing"] = len(missing_critical)
    policy = root / "AGENTS.md"
    try:
        if "docs/governance/a15-control-plane-only.md" not in policy.read_text(encoding="utf-8"):
            problems["agent_policy_reference_missing"] += 1
    except (OSError, UnicodeError):
        problems["agent_policy_reference_missing"] += 1
    hard_fail = any(problems.get(label, 0) for label in (
        "critical_reference_missing", "agent_policy_reference_missing",
        "tracked_file_missing", "untrusted_tracked_path",
    ))
    # Parse errors, symlinks and unknown formats are reported as real
    # findings; they are *not* automatically presumed malicious/defective.
    return {
        "schema": SCHEMA,
        "repository": "zenindiones-maker/BR-no-GTA",
        "head": head,
        "scope": "ALL_TRACKED_PATHS_METADATA_AND_BOUNDED_PYTHON_AST",
        "tracked_count": len(paths),
        "categories": dict(sorted(counts.items())),
        "anomalies": dict(sorted(problems.items())),
        "critical_references_present": not missing_critical,
        "critical_integrity": "FAIL" if hard_fail else "PASS",
        "rea6_provider_called": False,
        "ghidra_executed": False,
        "runtime_executed": False,
        "owner_voice_accessed": False,
        "promoted": False,
        "conclusion": "STATIC_INVENTORY_ONLY_NOT_FULL_REVERSE_ENGINEERING",
    }


def permitted_execution_host(environment: dict[str, str], *, root: Path) -> bool:
    """Keep even source scanning off the owner's Termux control device."""
    if (
        environment.get("PREFIX", "").startswith("/data/data/com.termux/")
        or str(root).startswith("/data/data/com.termux/")
    ):
        return False
    if environment.get("GITHUB_ACTIONS") == "true":
        return environment.get("GITHUB_WORKFLOW") == "BR V23 Isolated Owner Voice Contracts"
    return (
        environment.get("CODESPACES") == "true"
        and environment.get("CODESPACE_NAME") == "br-v23-recovery-gxp67g5g7wphwxjw"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-critical", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    if not permitted_execution_host(dict(os.environ), root=root):
        print("BR_V23_SOURCE_SWEEP=BLOCKED:CONTROL_DEVICE_OR_UNAUTHORIZED_HOST", file=sys.stderr)
        return 2
    try:
        result = inventory(root)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 2 if args.gate_critical and result["critical_integrity"] != "PASS" else 0
    except (OSError, ValueError, subprocess.CalledProcessError):
        print("BR_V23_SOURCE_SWEEP=BLOCKED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
