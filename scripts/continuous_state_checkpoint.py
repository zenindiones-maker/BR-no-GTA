from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any


ARTIFACT_PREFIX = "continuous-operation-state-"
ATTEMPT_ARTIFACT_PREFIX = "continuous-operation-attempt-"
DEFAULT_EXECUTOR_WORKFLOW = "continuous-intelligence-executor.yml"
LEGACY_WORKFLOW = "continuous-intelligence-operation.yml"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _run(*args: str) -> str:
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"command failed: {' '.join(args)}: {detail[:1000]}")
    return (result.stdout or "").strip()


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _workflow_candidates(primary: str) -> tuple[str, ...]:
    first = str(primary or DEFAULT_EXECUTOR_WORKFLOW).strip()
    values = [first]
    if LEGACY_WORKFLOW not in values:
        values.append(LEGACY_WORKFLOW)
    return tuple(values)


def _list_runs(
    *,
    repository: str,
    workflow: str,
    status: str | None = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    args = [
        "gh", "run", "list",
        "--repo", repository,
        "--workflow", workflow,
        "--limit", str(limit),
        "--json", "databaseId,headBranch,conclusion,createdAt",
    ]
    if status:
        args.extend(["--status", status])
    try:
        raw = _run(*args)
    except RuntimeError:
        return []
    value = json.loads(raw or "[]")
    return [dict(row) for row in value if isinstance(row, dict)]


def validate_checkpoint_manifest(
    manifest: dict[str, Any],
    *,
    database_sha256: str,
) -> bool:
    target_sha = str(manifest.get("target_sha") or "").strip().lower()
    digest = str(manifest.get("database_sha256") or "").strip().lower()
    return (
        manifest.get("schema") == "continuous-operation-state/v1"
        and _SHA40.fullmatch(target_sha) is not None
        and _SHA256.fullmatch(digest) is not None
        and digest == str(database_sha256 or "").strip().lower()
        and manifest.get("canonical_memory_plane") == "BR_SQLITE"
        and manifest.get("artifact_is_second_memory_plane") is False
    )


def validate_attempt_payload(payload: dict[str, Any]) -> bool:
    target_sha = str(payload.get("target_sha") or "").strip().lower()
    status = str(payload.get("status") or "").strip()
    if (
        payload.get("schema") != "ContinuousOperationAttempt/v1"
        or _SHA40.fullmatch(target_sha) is None
        or status not in {"PASS", "FAIL", "HELD_KNOWN_DEFECT"}
    ):
        return False
    if status in {"FAIL", "HELD_KNOWN_DEFECT"}:
        fingerprint = str(payload.get("failure_fingerprint") or "").strip().lower()
        if _SHA256.fullmatch(fingerprint) is None:
            return False
        if not str(payload.get("failure_class") or "").strip():
            return False
        if not str(payload.get("retryability") or "").strip():
            return False
    return True


def _download_named_artifact(
    *,
    repository: str,
    run_id: int,
    artifact_name: str,
    destination: Path,
) -> bool:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "gh", "run", "download", str(run_id),
            "--repo", repository,
            "--name", artifact_name,
            "--dir", str(destination),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def restore(
    *,
    repository: str,
    current_run_id: int,
    destination: Path,
    work_dir: Path,
    workflow: str = DEFAULT_EXECUTOR_WORKFLOW,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    for workflow_name in _workflow_candidates(workflow):
        rows = _list_runs(
            repository=repository,
            workflow=workflow_name,
            status="success",
            limit=60,
        )
        for row in rows:
            run_id = int(row.get("databaseId") or 0)
            if run_id <= 0 or run_id == current_run_id:
                continue
            artifact_name = f"{ARTIFACT_PREFIX}{run_id}"
            candidate_dir = work_dir / str(run_id)
            if not _download_named_artifact(
                repository=repository,
                run_id=run_id,
                artifact_name=artifact_name,
                destination=candidate_dir,
            ):
                continue
            db = candidate_dir / "continuous.db"
            manifest_path = candidate_dir / "state-manifest.json"
            if not db.is_file() or not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            digest = _sha(db)
            if not isinstance(manifest, dict) or not validate_checkpoint_manifest(
                manifest,
                database_sha256=digest,
            ):
                continue
            destination.write_bytes(db.read_bytes())
            return {
                "status": "RESTORED",
                "source_run_id": run_id,
                "source_workflow": workflow_name,
                "source_artifact": artifact_name,
                "database_sha256": _sha(destination),
                "canonical_memory_plane": "BR_SQLITE",
            }
    return {
        "status": "EMPTY_BOOTSTRAP",
        "source_run_id": None,
        "source_workflow": None,
        "source_artifact": None,
        "database_sha256": None,
        "canonical_memory_plane": "BR_SQLITE",
    }


def restore_attempt(
    *,
    repository: str,
    current_run_id: int,
    destination: Path,
    work_dir: Path,
    workflow: str = DEFAULT_EXECUTOR_WORKFLOW,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    for workflow_name in _workflow_candidates(workflow):
        rows = _list_runs(
            repository=repository,
            workflow=workflow_name,
            status=None,
            limit=80,
        )
        for row in rows:
            run_id = int(row.get("databaseId") or 0)
            if run_id <= 0 or run_id == current_run_id:
                continue
            artifact_name = f"{ATTEMPT_ARTIFACT_PREFIX}{run_id}"
            candidate_dir = work_dir / str(run_id)
            if not _download_named_artifact(
                repository=repository,
                run_id=run_id,
                artifact_name=artifact_name,
                destination=candidate_dir,
            ):
                continue
            attempt_path = candidate_dir / "continuous-operation-attempt.json"
            if not attempt_path.is_file():
                continue
            try:
                payload = json.loads(attempt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict) or not validate_attempt_payload(payload):
                continue
            destination.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            return {
                "status": "RESTORED",
                "source_run_id": run_id,
                "source_workflow": workflow_name,
                "source_artifact": artifact_name,
                "target_sha": payload["target_sha"],
                "attempt_status": payload["status"],
                "failure_fingerprint": payload.get("failure_fingerprint"),
            }

    if destination.exists():
        destination.unlink()
    return {
        "status": "NONE",
        "source_run_id": None,
        "source_workflow": None,
        "source_artifact": None,
        "target_sha": None,
        "attempt_status": None,
        "failure_fingerprint": None,
    }


def save(*, database: Path, output_dir: Path, target_sha: str, run_id: int) -> dict[str, Any]:
    normalized_sha = str(target_sha or "").strip().lower()
    if _SHA40.fullmatch(normalized_sha) is None:
        raise ValueError("target_sha must be an exact git sha")
    if not database.is_file():
        raise FileNotFoundError(f"continuous database missing: {database}")
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "continuous.db"
    if database.resolve() != target.resolve():
        target.write_bytes(database.read_bytes())
    manifest = {
        "schema": "continuous-operation-state/v1",
        "run_id": run_id,
        "target_sha": normalized_sha,
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
    restore_cmd.add_argument("--workflow", default=DEFAULT_EXECUTOR_WORKFLOW)

    attempt_cmd = sub.add_parser("restore-attempt")
    attempt_cmd.add_argument("--repository", required=True)
    attempt_cmd.add_argument("--current-run-id", type=int, required=True)
    attempt_cmd.add_argument("--destination", required=True)
    attempt_cmd.add_argument("--work-dir", required=True)
    attempt_cmd.add_argument("--workflow", default=DEFAULT_EXECUTOR_WORKFLOW)

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
            workflow=args.workflow,
        )
        print("CONTINUOUS_STATE_RESTORE=" + result["status"])
        if result.get("source_workflow"):
            print("CONTINUOUS_STATE_SOURCE_WORKFLOW=" + str(result["source_workflow"]))
    elif args.command == "restore-attempt":
        result = restore_attempt(
            repository=args.repository,
            current_run_id=args.current_run_id,
            destination=Path(args.destination),
            work_dir=Path(args.work_dir),
            workflow=args.workflow,
        )
        print("CONTINUOUS_ATTEMPT_RESTORE=" + result["status"])
        if result.get("attempt_status"):
            print("CONTINUOUS_PRIOR_ATTEMPT_STATUS=" + str(result["attempt_status"]))
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
