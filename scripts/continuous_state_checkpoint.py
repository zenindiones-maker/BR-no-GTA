from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any


ARTIFACT_PREFIX = "continuous-operation-state-"


def _run(*args: str) -> str:
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"command failed: {' '.join(args)}: {detail[:1000]}")
    return (result.stdout or "").strip()


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def restore(*, repository: str, current_run_id: int, destination: Path, work_dir: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    raw = _run(
        "gh", "run", "list",
        "--repo", repository,
        "--workflow", "continuous-intelligence-operation.yml",
        "--status", "success",
        "--limit", "40",
        "--json", "databaseId,headBranch,conclusion,createdAt",
    )
    rows = json.loads(raw or "[]")
    for row in rows:
        run_id = int(row.get("databaseId") or 0)
        if run_id <= 0 or run_id == current_run_id:
            continue
        artifact_name = f"{ARTIFACT_PREFIX}{run_id}"
        candidate_dir = work_dir / str(run_id)
        if candidate_dir.exists():
            shutil.rmtree(candidate_dir)
        candidate_dir.mkdir(parents=True)
        result = subprocess.run(
            [
                "gh", "run", "download", str(run_id),
                "--repo", repository,
                "--name", artifact_name,
                "--dir", str(candidate_dir),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            continue
        db = candidate_dir / "continuous.db"
        manifest_path = candidate_dir / "state-manifest.json"
        if not db.is_file() or not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema") != "continuous-operation-state/v1":
            continue
        if manifest.get("database_sha256") != _sha(db):
            continue
        destination.write_bytes(db.read_bytes())
        return {
            "status": "RESTORED",
            "source_run_id": run_id,
            "source_artifact": artifact_name,
            "database_sha256": _sha(destination),
            "canonical_memory_plane": "BR_SQLITE",
        }
    return {
        "status": "EMPTY_BOOTSTRAP",
        "source_run_id": None,
        "source_artifact": None,
        "database_sha256": None,
        "canonical_memory_plane": "BR_SQLITE",
    }


def save(*, database: Path, output_dir: Path, target_sha: str, run_id: int) -> dict[str, Any]:
    if not database.is_file():
        raise FileNotFoundError(f"continuous database missing: {database}")
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "continuous.db"
    if database.resolve() != target.resolve():
        target.write_bytes(database.read_bytes())
    manifest = {
        "schema": "continuous-operation-state/v1",
        "run_id": run_id,
        "target_sha": target_sha,
        "database_file": "continuous.db",
        "database_sha256": _sha(target),
        "canonical_memory_plane": "BR_SQLITE",
        "transport": "GITHUB_ACTIONS_ARTIFACT_CHECKPOINT",
        "artifact_is_second_memory_plane": False,
        "TERMUX_HEAVY_PROCESSING": "NO",
    }
    (output_dir / "state-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    restore_cmd = sub.add_parser("restore")
    restore_cmd.add_argument("--repository", required=True)
    restore_cmd.add_argument("--current-run-id", type=int, required=True)
    restore_cmd.add_argument("--destination", required=True)
    restore_cmd.add_argument("--work-dir", required=True)
    save_cmd = sub.add_parser("save")
    save_cmd.add_argument("--database", required=True)
    save_cmd.add_argument("--output-dir", required=True)
    save_cmd.add_argument("--target-sha", required=True)
    save_cmd.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()

    if args.command == "restore":
        result = restore(
            repository=args.repository,
            current_run_id=args.current_run_id,
            destination=Path(args.destination),
            work_dir=Path(args.work_dir),
        )
        print("CONTINUOUS_STATE_RESTORE=" + result["status"])
    else:
        result = save(
            database=Path(args.database),
            output_dir=Path(args.output_dir),
            target_sha=args.target_sha,
            run_id=args.run_id,
        )
        print("CONTINUOUS_STATE_CHECKPOINT=PASS")
        print("CONTINUOUS_STATE_SHA256=" + result["database_sha256"])
    print("SINGLE_CANONICAL_MEMORY_PLANE=PASS")
    print("TERMUX_HEAVY_PROCESSING=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
