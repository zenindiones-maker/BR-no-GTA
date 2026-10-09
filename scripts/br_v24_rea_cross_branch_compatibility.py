#!/usr/bin/env python3
"""Inspect EXACT historical BR REA source without importing or resurrecting it.

AST and source-file evidence, NOT an agent, not a second REA runtime.
Only same-repository first-party V4 vs V24, never third-party execution.
"""
from __future__ import annotations

import argparse
import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess

V4_SHA = "ad00c215ecd33ee74703cfeb0d72694220b666f0"
REPO = "zenindiones-maker/BR-no-GTA"
BRANCH = "work/br-slm-agent-reconstruction-v24"
WORKFLOW = "BR V24 Native REA Cross Branch Compatibility"
FILES = (
    "app/services/reverse_engineering_audio_v3_service.py",
    "app/services/reverse_engineering_experiment_intelligence_v4.py",
    "app/services/reverse_engineering_forensics_service.py",
    "app/services/reverse_engineering_harness_service.py",
    "app/services/reverse_engineering_learning_proposal_service.py",
    "app/services/reverse_engineering_longform_coverage_service.py",
    "app/services/reverse_engineering_media_service.py",
    "app/services/reverse_engineering_scene_v3_service.py",
    "app/services/reverse_engineering_story_service.py",
    "app/services/reverse_engineering_web_har_service.py",
    "scripts/br_reverse_engineering_harness.py",
    "scripts/br_reverse_engineering_observe.py",
    "tests/test_reverse_engineering_experiment_harness_v4.py",
    "tests/test_reverse_engineering_experiment_intelligence_v4.py",
    "tests/test_reverse_engineering_harness_v2.py",
    "tests/test_reverse_engineering_learning_proposal_v1.py",
    "tests/test_reverse_engineering_longform_coverage.py",
    "tests/test_reverse_engineering_media_service.py",
    "tests/test_reverse_engineering_multimodal_v3.py",
    "tests/test_reverse_engineering_story_v1.py",
    "tests/test_reverse_engineering_web_har_v3.py",
)


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _source(path: Path, root: Path):
    resolved_root = root.resolve(strict=True)
    # No symlink, paths must remain beneath their approved checkout.
    if path.is_symlink() or path.resolve(strict=False).parent == Path("/") or not path.is_file():
        return {"present": False}
    resolved = path.resolve(strict=True)
    if resolved_root not in resolved.parents:
        raise PermissionError("REA_SOURCE_PATH_ESCAPE")
    if resolved.stat().st_size > 2_000_000:
        raise ValueError("REA_SOURCE_OVERSIZED")
    raw = resolved.read_bytes()
    astree = ast.parse(raw, filename=str(path))
    api = []
    imports = []
    for node in astree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            api.append(node.name)
        elif isinstance(node, ast.ImportFrom):
            imports.append("." * node.level + str(node.module or ""))
        elif isinstance(node, ast.Import):
            imports.extend(name.name for name in node.names)
    return {
        "present": True,
        "sha256": _digest(raw),
        "bytes": len(raw),
        "public_top_level_symbols": sorted(set(api)),
        "imports": sorted(set(imports)),
    }


def compare(legacy_root: Path, current_root: Path):
    if len(FILES) != len(set(FILES)):
        raise ValueError("REA_DUPLICATE_MANIFEST")
    rows = []
    for name in FILES:
        old = _source(legacy_root / name, legacy_root)
        new = _source(current_root / name, current_root)
        if not old["present"]:
            status = "HISTORICAL_PROVENANCE_MISSING"
        elif not new["present"]:
            status = "HISTORICAL_ONLY_NOT_IN_V24"
        elif old["sha256"] == new["sha256"]:
            status = "IDENTICAL_IN_V24"
        else:
            status = "DIFF_REVIEW_REQUIRED"
        rows.append({
            "path": name,
            "status": status,
            "v4": old,
            "v24": new,
            "source_reintroduced": False,
        })
    from collections import Counter
    states = dict(sorted(Counter(x["status"] for x in rows).items()))
    return {
        "schema": "BRNativeREACrossBranchSourceCompatibility/v24",
        "old_commit": V4_SHA,
        "source_branch": "work/br-reverse-engineering-experiment-intelligence-v4",
        "destination_branch": BRANCH,
        "comparison": "FIRST_PARTY_SAME_REPO_AST_AND_HASH",
        "inspection_count": len(rows),
        "status_counts": states,
        "rows": rows,
        "runtime_invoked": False,
        "model_invoked": False,
        "upstream_rea_invoked": False,
        "ghidra_invoked": False,
        "git_files_mutated": False,
        "source_reintroduced": False,
        "authorization_changes": False,
        "a15_compute": False,
        "hazewave_mixed": False,
        "readiness": "COMPATIBILITY_REVIEW_REQUIRED",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source-root", required=True, type=Path)
    p.add_argument("--current-root", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    env = os.environ
    if (env.get("GITHUB_ACTIONS") != "true"
        or env.get("GITHUB_REPOSITORY") != REPO
        or env.get("GITHUB_WORKFLOW") != WORKFLOW
        or env.get("GITHUB_REF_NAME") != BRANCH
        or env.get("PREFIX", "").startswith("/data/data/com.termux/")):
        raise PermissionError("BR_REA_REMOTE_SAME_REPO_ONLY")
    current = args.current_root.resolve(strict=True)
    legacy = args.source_root.resolve(strict=True)
    if legacy == current or legacy in current.parents or current in legacy.parents:
        raise PermissionError("BR_REA_WORKTREES_NOT_ISOLATED")
    if subprocess.check_output(["git","-C",str(legacy),"rev-parse","HEAD"],text=True).strip() != V4_SHA:
        raise PermissionError("BR_REA_HISTORICAL_HEAD_MISMATCH")
    observed = subprocess.check_output(["git","-C",str(current),"rev-parse","HEAD"],text=True).strip()
    if observed != env.get("GITHUB_SHA"):
        raise PermissionError("BR_REA_V24_HEAD_MISMATCH")
    results = compare(legacy,current)
    if results["status_counts"].get("HISTORICAL_PROVENANCE_MISSING"):
        raise RuntimeError("BR_REA_EXPECTED_HISTORICAL_FILES_MISSING")
    results["current_head"] = observed
    results["receipt_sha256"] = _digest(json.dumps(results, sort_keys=True,ensure_ascii=False).encode())
    dest = args.output.resolve(strict=False)
    temp = Path(env["RUNNER_TEMP"]).resolve(strict=True)
    if dest.parent != temp or dest.suffix != ".json" or dest.exists() or dest.is_symlink():
        raise PermissionError("BR_REA_OUTPUT_NOT_RUNNER_TEMP")
    fd = os.open(dest, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as stream:
        json.dump(results,stream,indent=2,sort_keys=True,ensure_ascii=False)
        stream.write("\n")
    print("BR_NATIVE_REA_LEGACY_PIN=PASS")
    print("BR_NATIVE_REA_V24_SOURCE_COUNTS="+json.dumps(results["status_counts"],sort_keys=True))
    print("BR_NATIVE_REA_REINTRODUCED=FALSE")
    print("BR_NATIVE_REA_RUNTIME=NOT_ATTEMPTED")
    print("BR_NATIVE_REA_COMPAT_RECEIPT="+results["receipt_sha256"])


if __name__ == "__main__":
    main()
