#!/usr/bin/env python3
"""Static integrity sweep of all DECLARED BR-native Registry executor bindings.

No modules are dynamically imported, no functions invoked. This avoids
surprising import-time side effects on secret-bearing or remote providers.
A passing AST contract is NOT a proof that runtime execution is healthy.
"""
from __future__ import annotations

from collections import Counter
import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SCHEMA = "BRV24AllDeclaredExecutorBindingsAST/v1"
REPO = "zenindiones-maker/BR-no-GTA"
BRANCH = "work/br-slm-agent-reconstruction-v24"
WORKFLOW = "BR V24 Complete Executor Binding Integrity"
QUALIFIED = re.compile(r"^[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*){2,}$")


def inspect_binding(root: Path, binding: str):
    if not isinstance(binding, str) or not QUALIFIED.fullmatch(binding):
        return "UNRESOLVED_BINDING_SYNTAX"
    parts = binding.split(".")
    if parts[0] != "app" or parts[1] != "services":
        return "NON_SERVICE_OR_NONPYTHON_BINDING"
    # Find longest existing Python module prefix; remaining segments refer
    # to functions/classes/members. No import hooks or remote calls.
    found = None
    for n in range(len(parts) - 1, 2, -1):
        candidate = root.joinpath(*parts[:n]).with_suffix(".py")
        if candidate.is_file() and not candidate.is_symlink():
            found = candidate, parts[n:]
            break
    if found is None:
        return "SOURCE_MODULE_NOT_FOUND"
    path, symbols = found
    if path.stat().st_size > 2 * 1024 * 1024:
        return "SOURCE_TOO_LARGE"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeError, OSError):
        return "SOURCE_PARSE_ERROR"
    children = tree.body
    for name in symbols:
        match = next((n for n in children if isinstance(n, (
            ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
        )) and n.name == name), None)
        if match is not None:
            if isinstance(match, ast.ClassDef):
                children = match.body
                continue
            if name != symbols[-1]:
                return "NON_CLASS_INTERMEDIATE_SYMBOL"
            return "STATIC_SYMBOL_FOUND"
        # Re-exported/assigned symbols need a separate live import test;
        # never claim MISSING if static AST cannot decide.
        assigned = any(
            isinstance(n, (ast.Assign, ast.AnnAssign, ast.ImportFrom, ast.Import))
            for n in children
        )
        return "STATIC_SYMBOL_UNRESOLVED_POSSIBLE_REEXPORT" if assigned else "STATIC_SYMBOL_NOT_FOUND"
    return "STATIC_SYMBOL_FOUND"


def check_all(root: Path, records):
    selected = [r for r in records if r.execution_enabled]
    if len(selected) > 10000 or len({r.capability_id for r in selected}) != len(selected):
        raise ValueError("BR_EXECUTOR_BOUNDS_OR_DUPLICATES")
    result = []
    for r in sorted(selected, key=lambda x: x.capability_id):
        binding = str(r.executor_binding or "")
        result.append({
            "capability_id": r.capability_id,
            "binding": binding,
            "status": inspect_binding(root, binding),
            "execution_attempted": False,
        })
    counts = dict(sorted(Counter(r["status"] for r in result).items()))
    return {
        "schema": SCHEMA,
        "declared_executors": len(selected),
        "binding_status_counts": counts,
        "results": result,
        "runtime_proven": False,
        "external_provider_proven": False,
        "model_inference": False,
        "a15_compute": False,
        "no_agent_creation": True,
    }


def main():
    e = os.environ
    if (e.get("GITHUB_ACTIONS") != "true"
            or e.get("GITHUB_REPOSITORY") != REPO
            or e.get("GITHUB_WORKFLOW") != WORKFLOW
            or e.get("GITHUB_REF_NAME") != BRANCH
            or e.get("PREFIX", "").startswith("/data/data/com.termux/")):
        raise SystemExit("BR_EXECUTOR_AUDIT_REMOTE_ONLY")
    root = Path(__file__).resolve().parents[1]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if head != e.get("GITHUB_SHA"):
        raise SystemExit("BR_EXECUTOR_AUDIT_SHA_DRIFT")
    sys.path.insert(0, str(root))
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
    result = check_all(root, GLOBAL_CAPABILITY_REGISTRY.all())
    result["head"] = head
    result["sha256"] = sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    dirpath = Path(e["RUNNER_TEMP"]).resolve()
    out = dirpath / ("br-v24-executor-integrity-" + head + ".json")
    if not dirpath.is_dir() or out.exists() or out.is_symlink():
        raise SystemExit("BR_EXECUTOR_AUDIT_OUTPUT_INVALID")
    fd = os.open(out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.write("\n")
    print("BR_V24_EXECUTOR_DECLARED=" + str(result["declared_executors"]))
    print("BR_V24_EXECUTOR_STATIC_COUNTS=" + json.dumps(result["binding_status_counts"],sort_keys=True))
    for record in result["results"]:
        if record["status"] != "STATIC_SYMBOL_FOUND":
            print("BR_V24_EXECUTOR_FINDING=" + record["capability_id"] + ":" + record["status"])
    print("BR_V24_EXECUTOR_STATIC_RECEIPT_SHA256=" + result["sha256"])
    print("BR_V24_EXECUTOR_RUNTIME=NOT_VERIFIED_BY_AST")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
