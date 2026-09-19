from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request
import shutil
import subprocess

from app.database.schema import initialize_schema
from app.services.e2e_stage_checkpoint_service import build_resume_plan
from app.services.e2e_stage_spec_service import (
    bootstrap_checkpoints,
    build_specs_from_artifacts,
)


def _get_json(url: str, token: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "BR-no-GTA-e2e-resume/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _find_source_runs(*, repo: str, current_run_id: int, branch: str, token: str) -> list[dict]:
    current = _get_json(f"https://api.github.com/repos/{repo}/actions/runs/{current_run_id}", token)
    workflow_id = current.get("workflow_id")
    if not workflow_id:
        return None
    query = urllib.parse.urlencode({"branch": branch, "status": "completed", "per_page": 30})
    payload = _get_json(
        f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_id}/runs?{query}",
        token,
    )
    found: list[dict] = []
    for run in payload.get("workflow_runs") or ():
        run_id = int(run.get("id") or 0)
        if run_id <= 0 or run_id == current_run_id:
            continue
        if run.get("conclusion") not in {"success", "failure"}:
            continue
        artifacts = _get_json(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts", token)
        expected = f"real-multi-agent-synergy-{run_id}"
        artifact = next(
            (
                item
                for item in artifacts.get("artifacts") or ()
                if item.get("name") == expected and not item.get("expired")
            ),
            None,
        )
        if artifact is not None:
            found.append({"run": run, "artifact": artifact})
    return found


def _download_artifact_with_gh(
    *,
    repo: str,
    run_id: int,
    artifact_name: str,
    destination: Path,
) -> list[str]:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(
        [
            "gh", "run", "download", str(run_id),
            "--repo", repo,
            "--name", artifact_name,
            "--dir", str(destination),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        safe = "\n".join(
            line
            for line in (process.stderr or "").splitlines()
            if "token" not in line.casefold() and "authorization" not in line.casefold()
        )[-2000:]
        raise RuntimeError(f"artifact download failed via gh: {safe or 'unknown error'}")
    allowed = {
        "mission.db",
        "fresh-research.json",
        "multi-agent-proof.json",
        "product-quality-e2e.json",
        "performance-report.json",
        "performance-trace.jsonl",
    }
    found = sorted({path.name for path in destination.rglob("*") if path.is_file() and path.name in allowed})
    for name in found:
        source = next(destination.rglob(name))
        if source.parent != destination:
            target = destination / name
            target.write_bytes(source.read_bytes())
    return found


def _trace_durations(path: Path) -> dict[str, float]:
    if not path.is_file():
        return {}
    mapping = {
        "agent.gta6-brain": "gta6-brain",
        "agent.content-strategy": "content-strategy",
        "product.editorial_script": "editorial-script",
        "agent.script-review-product": "script-review",
        "agent.seo-product": "seo",
        "agent.production-product": "production-management",
        "agent.thumbnail-product": "thumbnail",
    }
    result: dict[str, float] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        item = json.loads(raw)
        stage_id = mapping.get(str(item.get("stage") or ""))
        if stage_id:
            result[stage_id] = max(result.get(stage_id, 0.0), float(item.get("duration_ms") or 0.0))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, default=Path("runtime/real-multi-agent-synergy"))
    parser.add_argument("--force-full", action="store_true")
    args = parser.parse_args()

    current_run_id = int(os.getenv("GITHUB_RUN_ID") or 0)
    repo = str(os.getenv("GITHUB_REPOSITORY") or "").strip()
    branch = str(os.getenv("GITHUB_REF_NAME") or "").strip()
    token = str(os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    if args.force_full or os.getenv("BR_E2E_FORCE_FULL", "").strip().lower() in {"1", "true", "yes"}:
        result = {
            "mode": "FULL_PROOF_RUN",
            "resume_available": False,
            "RESUME_FROM_STAGE": "research",
            "REUSED_STAGE_COUNT": 0,
            "RECOMPUTED_STAGE_COUNT": 10,
            "REUSED_TIME_SAVED_MS": 0.0,
        }
    elif not token or repo.count("/") != 1 or current_run_id <= 0:
        result = {
            "mode": "FULL_PROOF_RUN",
            "resume_available": False,
            "reason": "RUNTIME_IDENTITY_UNAVAILABLE",
            "RESUME_FROM_STAGE": "research",
            "REUSED_STAGE_COUNT": 0,
            "RECOMPUTED_STAGE_COUNT": 10,
            "REUSED_TIME_SAVED_MS": 0.0,
        }
    else:
        sources = _find_source_runs(repo=repo, current_run_id=current_run_id, branch=branch, token=token)
        source = sources[0] if sources else None
        if source is None:
            result = {
                "mode": "FULL_PROOF_RUN",
                "resume_available": False,
                "reason": "NO_PRIOR_ARTIFACT",
                "RESUME_FROM_STAGE": "research",
                "REUSED_STAGE_COUNT": 0,
                "RECOMPUTED_STAGE_COUNT": 10,
                "REUSED_TIME_SAVED_MS": 0.0,
            }
        else:
            source_run = source["run"]
            artifact = source["artifact"]
            source_dir = args.runtime_dir / "resume-source"
            extracted = _download_artifact_with_gh(
                repo=repo,
                run_id=int(source_run["id"]),
                artifact_name=str(artifact["name"]),
                destination=source_dir,
            )
            required = {"mission.db", "fresh-research.json", "multi-agent-proof.json", "product-quality-e2e.json"}
            if not required <= set(extracted):
                result = {
                    "mode": "FULL_PROOF_RUN",
                    "resume_available": False,
                    "reason": "PRIOR_ARTIFACT_INCOMPLETE",
                    "source_run_id": source_run.get("id"),
                    "extracted": extracted,
                    "RESUME_FROM_STAGE": "research",
                    "REUSED_STAGE_COUNT": 0,
                    "RECOMPUTED_STAGE_COUNT": 10,
                    "REUSED_TIME_SAVED_MS": 0.0,
                }
            else:
                args.runtime_dir.mkdir(parents=True, exist_ok=True)
                for name in required:
                    (args.runtime_dir / name).write_bytes((source_dir / name).read_bytes())
                os.environ["BR_TEST_DATABASE"] = str((args.runtime_dir / "mission.db").resolve())
                initialize_schema()
                fresh = json.loads((args.runtime_dir / "fresh-research.json").read_text(encoding="utf-8"))
                proof = json.loads((args.runtime_dir / "multi-agent-proof.json").read_text(encoding="utf-8"))
                product = json.loads((args.runtime_dir / "product-quality-e2e.json").read_text(encoding="utf-8"))
                durations = _trace_durations(source_dir / "performance-trace.jsonl")
                bootstrap = bootstrap_checkpoints(
                    fresh=fresh,
                    proof=proof,
                    product=product,
                    source_commit_sha=str(source_run.get("head_sha") or ""),
                    source_run_id=str(source_run.get("id") or ""),
                    durations_ms=durations,
                )
                specs = build_specs_from_artifacts(fresh=fresh, proof=proof, product=product)
                plan = build_resume_plan(goal_id=bootstrap["goal_id"], specs=specs)
                reusable_upstream = {
                    "research", "fact-check", "gta6-brain", "content-strategy"
                } <= set(plan["reused_stages"])
                result = {
                    "mode": "TARGETED_RETRY_RUN",
                    "resume_available": True,
                    "source_run_id": source_run.get("id"),
                    "source_head_sha": source_run.get("head_sha"),
                    "artifact_id": artifact.get("id"),
                    "bootstrap": bootstrap,
                    **plan,
                    "reuse_upstream": reusable_upstream,
                    "reuse_product_package": "youtube-package" in set(plan["reused_stages"]),
                }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for key in (
        "mode",
        "RESUME_FROM_STAGE",
        "REUSED_STAGE_COUNT",
        "RECOMPUTED_STAGE_COUNT",
        "REUSED_TIME_SAVED_MS",
    ):
        print(f"{key}={result.get(key)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
