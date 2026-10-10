#!/usr/bin/env python3
"""First-pass *static* BR-no-GTA system-wide surface inventory.

Examines only tracked first-party files. No imports of project modules, network,
execution of workflows, third-party executables, secrets, source contents in
receipts, mutation or claims of operational completeness.
"""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess


SOURCE_ROOTS = ("app/", "scripts/", "tests/", "video-engine/")
MAX_SOURCE_BYTES = 768 * 1024
MAX_FILES = 10000
EXCLUDED_SOURCE_PARTS = {
    ".local", ".venv", "node_modules", "vendor", "third_party", "upstreams",
}
REQUIRED_PATTERN = re.compile(r"\*\*Required:\*\*\s*`([^`]+)`|Required:\s*`([^`]+)`")
WORKFLOW_ACTION = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def tracked_sources(root: Path) -> list[str]:
    if not (root / "AGENTS.md").is_file():
        raise RuntimeError("AGENTS.md missing")
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True, capture_output=True, timeout=20,
    )
    entries = [name.decode("utf-8") for name in result.stdout.split(b"\x00") if name]
    if len(entries) > MAX_FILES:
        raise RuntimeError("Tracked file budget exceeded")
    return sorted(entries)


def audit(root: Path, paths: list[str]) -> dict:
    tracked = set(paths)
    issues: list[dict[str, str | int]] = []
    modules = 0
    dependencies = 0
    workflows = 0
    actions = 0
    policies = 0
    policy_source = (root / "AGENTS.md").read_text(encoding="utf-8")
    for match in REQUIRED_PATTERN.finditer(policy_source):
        item = match.group(1) or match.group(2)
        if item:
            policies += 1
            if item not in tracked:
                issues.append({
                    "kind": "POLICY_REFERENCE_MISSING",
                    "severity": "HIGH_CANDIDATE",
                    "path": item,
                })
    for relative in paths:
        path = root / relative
        if not path.is_file() or path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            continue
        if relative.startswith(".github/workflows/") and path.suffix in (".yml", ".yaml"):
            workflows += 1
            body = path.read_text(encoding="utf-8")
            if not re.search(r"^permissions\s*:", body, re.MULTILINE):
                issues.append({
                    "kind": "WORKFLOW_TOKEN_PERMISSIONS_UNVERIFIED",
                    "severity": "REVIEW",
                    "path": relative,
                })
            for action in WORKFLOW_ACTION.findall(body):
                actions += 1
                if action.startswith("./"):
                    continue
                revision = action.rsplit("@", 1)[-1] if "@" in action else ""
                if not FULL_SHA.fullmatch(revision):
                    issues.append({
                        "kind": "ACTION_NOT_PINNED_TO_FULL_SHA",
                        "severity": "REVIEW",
                        "path": relative,
                    })
        if not relative.endswith(".py") or not relative.startswith(SOURCE_ROOTS):
            continue
        if any(part in EXCLUDED_SOURCE_PARTS for part in Path(relative).parts):
            continue
        size = path.stat().st_size
        if size > MAX_SOURCE_BYTES:
            issues.append({
                "kind": "PYTHON_SOURCE_OVER_BUDGET",
                "severity": "REVIEW",
                "path": relative,
            })
            continue
        try:
            tree = ast.parse(path.read_bytes(), filename=relative)
        except (SyntaxError, UnicodeError, ValueError):
            issues.append({
                "kind": "PYTHON_AST_PARSE_FAILED",
                "severity": "HIGH_CANDIDATE",
                "path": relative,
            })
            continue
        modules += 1
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names if a.name.startswith(("app.", "scripts."))]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module.startswith(("app.", "scripts.")):
                    names = [node.module]
            for module in names:
                dependencies += 1
                target = module.replace(".", "/")
                # Namespace packages are allowed. This is not a Python import
                # resolver; only report a missing prefix when neither form exists.
                if (
                    target + ".py" not in tracked and
                    target + "/__init__.py" not in tracked and
                    not any(t.startswith(target + "/") for t in tracked)
                ):
                    issues.append({
                        "kind": "FIRST_PARTY_IMPORT_UNRESOLVED_CANDIDATE",
                        "severity": "REVIEW",
                        "path": relative,
                        "module": module,
                    })
    digest_payload = json.dumps(issues, sort_keys=True, separators=(",", ":")).encode()
    counts = dict(sorted(Counter(str(issue["kind"]) for issue in issues).items()))
    return {
        "schema": "BRSystemStaticSurfaceAudit/v1",
        "status": "OBSERVED_STATIC_NOT_RUNTIME_VERIFIED",
        "tracked_files": len(paths),
        "python_modules_parsed": modules,
        "observed_first_party_imports": dependencies,
        "workflows": workflows,
        "workflow_actions": actions,
        "required_policy_references_checked": policies,
        "candidate_counts": counts,
        "candidate_total": len(issues),
        "candidate_examples": issues[:30],
        "full_candidate_sha256": hashlib.sha256(digest_payload).hexdigest(),
        "explicitly_unverified": [
            "ARTEX runtime", "Owner Voice identity", "Telegram delivery",
            "YouTube private HD production", "Chrome DevTools remote E2E",
            "native REA V4 installation", "full operational health",
        ],
    }


if __name__ == "__main__":
    here = Path(__file__).resolve().parents[1]
    observed = audit(here, tracked_sources(here))
    print(json.dumps(observed, sort_keys=True, ensure_ascii=False))
    print("BR_SYSTEM_TRACKED_STATIC_SURFACE=OBSERVED")
