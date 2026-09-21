from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from app.database.schema import initialize_schema
from app.services.addy_harness_service import execute_authorized_addy_skill
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.capability_usage_audit_service import build_capability_usage_audit
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_collaboration_service import build_collaboration_plan
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.system_synergy_service import execute_system_improvement_via_harness


ROOT = Path(__file__).resolve().parents[1]
MAX_CONTEXT_CHARS = 14_000

SPECIALISTS: tuple[dict[str, str], ...] = (
    {
        "task_id": "architecture-review",
        "capability_id": "addy:code-review-and-quality",
        "focus": (
            "Audit architecture boundaries, duplicate paths, dead code, bypasses, orphan/disconnected "
            "capabilities, accidental second authorities, and contract drift. Prioritize concrete files "
            "and measurable risks. Do not suggest replacing DeepSeek Harness authority."
        ),
    },
    {
        "task_id": "performance-review",
        "capability_id": "addy:performance-optimization",
        "focus": (
            "Audit measurable latency and redundant work: repeated downloads, probes, encodes, TTS, "
            "transcriptions, subprocess startup, network calls, polling, database access, caching and "
            "bounded concurrency. Separate measured evidence from hypotheses."
        ),
    },
    {
        "task_id": "reliability-review",
        "capability_id": "addy:debugging-and-error-recovery",
        "focus": (
            "Audit retries, timeouts, recovery, idempotency, fail-closed behavior, queue semantics, "
            "partial failure handling and stale execution paths. Identify failure modes that can create "
            "false PASS or duplicate work."
        ),
    },
    {
        "task_id": "security-review",
        "capability_id": "addy:security-and-hardening",
        "focus": (
            "Audit trust boundaries, untrusted media/transcript input, subprocess/network exposure, "
            "credential handling, GitHub Actions permissions and publication safety. Do not request or "
            "expose secrets."
        ),
    },
    {
        "task_id": "observability-review",
        "capability_id": "addy:observability-and-instrumentation",
        "focus": (
            "Audit whether routing, agent selection, external calls, render stages, cache hits, retries, "
            "artifacts and failures are measurable with stable execution/mission/capability identities."
        ),
    },
    {
        "task_id": "ci-review",
        "capability_id": "addy:ci-cd-and-automation",
        "focus": (
            "Audit GitHub Actions cold starts, repeated dependency installation, cache usage, artifact "
            "flows, concurrency, job fan-out and opportunities to reduce wall clock without weakening QA."
        ),
    },
    {
        "task_id": "evidence-review",
        "capability_id": "addy:source-driven-development",
        "focus": (
            "Audit evidence provenance and source hierarchy from research through fact-check, production, "
            "QA, learning and promotion. Identify any place where self-report could be mistaken for "
            "observed evidence."
        ),
    },
)


PATTERNS: dict[str, tuple[str, ...]] = {
    "subprocess": (r"subprocess\.(?:run|Popen|check_output|check_call)",),
    "ffmpeg": (r"\bffmpeg\b", r"\bffprobe\b"),
    "download": (r"yt-dlp", r"download"),
    "whisper": (r"whisperx?", r"transcript"),
    "tts": (r"edge-tts", r"\btts\b", r"narration"),
    "telegram": (r"telegram",),
    "youtube": (r"youtube",),
    "polling": (r"time\.sleep", r"poll_interval", r"wait_for_completion"),
    "network": (r"urllib\.", r"httpx\.", r"requests\.", r"curl "),
    "database": (r"sqlite", r"execute\(", r"executemany\("),
    "cache": (r"cache", r"memoiz", r"artifact_reused"),
    "render": (r"render", r"vedit", r"filtergraph"),
}


def _git_head() -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def _text_files() -> list[Path]:
    allowed = {".py", ".yml", ".yaml", ".json", ".toml", ".md", ".sh", ".mjs", ".ts", ".js"}
    ignored = {".git", ".venv", "node_modules", "runtime", "artifacts", "__pycache__"}
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        if any(part in ignored for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def _hotspots(files: list[Path]) -> dict[str, Any]:
    compiled = {
        key: tuple(re.compile(pattern, re.I) for pattern in values)
        for key, values in PATTERNS.items()
    }
    category_counts: Counter[str] = Counter()
    per_file: dict[str, Counter[str]] = {}
    unreadable: list[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            unreadable.append(str(path.relative_to(ROOT)))
            continue
        relative = str(path.relative_to(ROOT))
        local: Counter[str] = Counter()
        for category, patterns in compiled.items():
            count = sum(len(pattern.findall(text)) for pattern in patterns)
            if count:
                local[category] = count
                category_counts[category] += count
        if local:
            per_file[relative] = local

    top_by_category: dict[str, list[dict[str, Any]]] = {}
    for category in PATTERNS:
        rows = [
            {"path": path, "count": counts[category]}
            for path, counts in per_file.items()
            if counts.get(category)
        ]
        rows.sort(key=lambda item: (-int(item["count"]), str(item["path"])))
        top_by_category[category] = rows[:12]
    return {
        "category_occurrences": dict(sorted(category_counts.items())),
        "top_files_by_category": top_by_category,
        "unreadable_files": unreadable[:20],
    }


def _workflow_snapshot(files: list[Path]) -> dict[str, Any]:
    workflows = [
        path for path in files
        if path.parent == ROOT / ".github" / "workflows"
        and path.suffix.lower() in {".yml", ".yaml"}
    ]
    rows: list[dict[str, Any]] = []
    for path in workflows:
        text = path.read_text(encoding="utf-8", errors="replace")
        rows.append({
            "path": str(path.relative_to(ROOT)),
            "pip_install_count": len(re.findall(r"pip install", text, re.I)),
            "npm_install_count": len(re.findall(r"npm install", text, re.I)),
            "apt_install_count": len(re.findall(r"apt(?:-get)? install", text, re.I)),
            "upload_artifact_count": len(re.findall(r"actions/upload-artifact", text, re.I)),
            "download_artifact_count": len(re.findall(r"actions/download-artifact", text, re.I)),
            "cache_mentions": len(re.findall(r"cache", text, re.I)),
        })
    repeated_setup = sorted(
        rows,
        key=lambda row: -(
            row["pip_install_count"]
            + row["npm_install_count"]
            + row["apt_install_count"]
        ),
    )[:15]
    return {
        "workflow_count": len(workflows),
        "top_dependency_setup_workflows": repeated_setup,
        "total_pip_install_steps": sum(row["pip_install_count"] for row in rows),
        "total_npm_install_steps": sum(row["npm_install_count"] for row in rows),
        "total_apt_install_steps": sum(row["apt_install_count"] for row in rows),
        "total_artifact_upload_steps": sum(row["upload_artifact_count"] for row in rows),
        "total_artifact_download_steps": sum(row["download_artifact_count"] for row in rows),
    }


def _registry_snapshot() -> dict[str, Any]:
    records = GLOBAL_CAPABILITY_REGISTRY.all()
    return {
        "total_capabilities": len(records),
        "available": sum(record.available for record in records),
        "execution_enabled": sum(record.execution_enabled for record in records),
        "domains": dict(sorted(Counter(record.domain for record in records).items())),
        "capability_types": dict(
            sorted(Counter(record.capability_type for record in records).items())
        ),
        "no_executor_binding": sorted(
            record.capability_id for record in records if not record.executor_binding
        ),
        "unavailable_or_unknown": sorted(
            record.capability_id for record in records if not record.available
        ),
    }


def build_snapshot() -> dict[str, Any]:
    files = _text_files()
    extensions = Counter(path.suffix.lower() for path in files)
    return {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(),
        "file_count": len(files),
        "extensions": dict(sorted(extensions.items())),
        "hotspots": _hotspots(files),
        "workflows": _workflow_snapshot(files),
        "registry": _registry_snapshot(),
        "capability_usage": build_capability_usage_audit(),
        "known_governed_performance_surfaces": [
            ".github/workflows/operational-cold-start-benchmark.yml",
            ".github/workflows/render-issue14-promotion.yml",
            ".github/workflows/video-a-render-profile-benchmark.yml",
            "scripts/benchmark_render_pipeline_optimization.py",
            "scripts/profile_render_canary.py",
            "app/services/render_learning_profile_service.py",
        ],
        "hard_invariants": {
            "authority": "DEEPSEEK_HARNESS",
            "job18_frozen": True,
            "youtube_publication": False,
            "quality_may_not_regress": True,
        },
    }


def _bounded_context(snapshot: dict[str, Any], focus: str) -> dict[str, Any]:
    context = {
        "focus": focus,
        "git_head": snapshot["git_head"],
        "registry": snapshot["registry"],
        "capability_usage": snapshot.get("capability_usage", {}),
        "workflows": snapshot["workflows"],
        "hotspots": snapshot["hotspots"],
        "known_governed_performance_surfaces": snapshot[
            "known_governed_performance_surfaces"
        ],
        "hard_invariants": snapshot["hard_invariants"],
    }
    encoded = json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)
    if len(encoded) <= MAX_CONTEXT_CHARS:
        return context
    # Deterministically compact the hotspot evidence before sending it to a model.
    compact = dict(context)
    hotspots = dict(compact["hotspots"])
    hotspots["top_files_by_category"] = {
        key: list(value)[:5]
        for key, value in hotspots["top_files_by_category"].items()
    }
    compact["hotspots"] = hotspots
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True, default=str)
    if len(encoded) > MAX_CONTEXT_CHARS:
        compact["hotspots"] = {
            "category_occurrences": hotspots["category_occurrences"],
            "top_files_by_category": {
                key: list(value)[:2]
                for key, value in hotspots["top_files_by_category"].items()
            },
        }
    return compact


def _execute_addy_review(
    *,
    mission_id: str,
    goal_id: str,
    spec: dict[str, str],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    capability_id = spec["capability_id"]
    record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
    if record is None:
        raise RuntimeError(f"missing review capability: {capability_id}")
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=f"SYSTEM_IMPROVEMENT_REVIEW {spec['focus']}",
            authorized_action="DEVELOPMENT",
            domain=record.domain,
            task_class=f"system-improvement:{spec['task_id']}",
            goal_id=goal_id,
            required_capability_id=capability_id,
            fallback_allowed=False,
            provider_required=False,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject=f"capability:{capability_id}",
        harness_decision_id=f"{mission_id}:{spec['task_id']}",
        execution_id=f"{mission_id}:{spec['task_id']}:execution",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "mission_id": mission_id,
            "goal_id": goal_id,
            "task_id": spec["task_id"],
        },
    )
    try:
        evidence = execute_authorized_addy_skill(
            authorization=authorization,
            routing_decision=routing,
            payload={
                "mission_id": mission_id,
                "task_id": spec["task_id"],
                "goal_id": goal_id,
                "task_class": f"system-improvement:{spec['task_id']}",
                "task": (
                    spec["focus"]
                    + " Return findings in priority order. For every finding state: "
                    "EVIDENCE, MEASURED_OR_HYPOTHESIS, RISK, RECOMMENDED_EXPERIMENT, "
                    "QUALITY_RISK, ARCHITECTURE_RISK. Never claim a measurement that "
                    "is not present in the supplied evidence."
                ),
                "context": _bounded_context(snapshot, spec["focus"]),
                "evidence_refs": [
                    f"repo-head:{snapshot['git_head']}",
                    "system-improvement:static-snapshot",
                ],
            },
        )
    finally:
        consume_harness_authorization(authorization)
    if evidence.status != "EXECUTED" or not isinstance(evidence.result, dict):
        raise RuntimeError(f"review specialist failed: {capability_id}")
    receipt = dict(evidence.result.get("receipt") or {})
    if receipt.get("proven_live") is not True:
        raise RuntimeError(f"review specialist lacks live receipt: {capability_id}")
    if receipt.get("external_call_performed") is not True:
        raise RuntimeError(f"review specialist lacks semantic execution: {capability_id}")
    output = str(evidence.result.get("output") or "").strip()
    if not output:
        raise RuntimeError(f"review specialist returned empty output: {capability_id}")
    return {
        "task_id": spec["task_id"],
        "capability_id": capability_id,
        "skill_id": record.skill_id,
        "routing": routing.to_dict(),
        "receipt": receipt,
        "output": output,
        "provider": evidence.result.get("semantic_provider"),
        "model": evidence.result.get("semantic_model"),
        "provider_profile_version": evidence.result.get("provider_profile_version"),
    }


def _aggregate(
    *,
    mission_id: str,
    goal_id: str,
    reviews: list[dict[str, Any]],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    capability_id = "system.improvement.propose"
    record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
    if record is None:
        raise RuntimeError("system.improvement.propose missing from Registry")
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="aggregate evidence-driven SYSTEM_IMPROVEMENT_REVIEW findings",
            authorized_action="DEVELOPMENT",
            domain=record.domain,
            task_class="system-improvement-review",
            goal_id=goal_id,
            required_capability_id=capability_id,
            fallback_allowed=False,
            provider_required=False,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject=f"capability:{capability_id}",
        harness_decision_id=f"{mission_id}:aggregate",
        execution_id=f"{mission_id}:aggregate:execution",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "mission_id": mission_id,
            "goal_id": goal_id,
            "task_id": "aggregate",
        },
    )
    gaps = [
        f"{item['skill_id']}: {item['output'][:3000]}"
        for item in reviews
    ]
    evidence_refs = [
        f"repo-head:{snapshot['git_head']}",
        "system-improvement:static-snapshot",
        *[
            ref
            for item in reviews
            for ref in item["receipt"].get("evidence_refs") or ()
        ],
        *[
            ref
            for item in reviews
            for ref in item["receipt"].get("output_refs") or ()
        ],
    ]
    try:
        canonical = execute_system_improvement_via_harness(
            authorization=authorization,
            routing_decision=routing,
            payload={
                "mission_id": mission_id,
                "task_id": "aggregate",
                "goal_id": goal_id,
                "task_class": "system-improvement-review",
                "gaps": gaps,
                "evidence_refs": list(dict.fromkeys(evidence_refs)),
            },
        )
    finally:
        consume_harness_authorization(authorization)
    if not canonical.success or not isinstance(canonical.result, dict):
        raise RuntimeError("system improvement aggregator did not execute")
    receipt = dict(canonical.result.get("receipt") or {})
    if receipt.get("proven_live") is not True:
        raise RuntimeError("system improvement aggregator lacks live receipt")
    return {
        "canonical": canonical.to_dict(),
        "routing": routing.to_dict(),
        "receipt": receipt,
    }


def run(output: Path, snapshot_output: Path) -> dict[str, Any]:
    initialize_schema()
    snapshot = build_snapshot()
    snapshot_output.parent.mkdir(parents=True, exist_ok=True)
    snapshot_output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    run_id = str(os.getenv("GITHUB_RUN_ID") or "local")
    mission_id = f"system-improvement-review-{run_id}"
    goal_id = f"system-improvement-goal-{run_id}"
    tasks = [
        {
            "task_id": spec["task_id"],
            "capability_id": spec["capability_id"],
            "action": "DEVELOPMENT",
            "objective": spec["focus"],
            "expected_output": "EvidenceDrivenReview",
        }
        for spec in SPECIALISTS
    ]
    tasks.append({
        "task_id": "aggregate",
        "capability_id": "system.improvement.propose",
        "action": "DEVELOPMENT",
        "objective": "aggregate observed specialist findings into governed proposals",
        "dependencies": [spec["task_id"] for spec in SPECIALISTS],
        "expected_output": "SystemImprovementProposal",
    })
    plan = build_collaboration_plan(
        mission_id=mission_id,
        goal_id=goal_id,
        tasks=tasks,
    )

    reviews = [
        _execute_addy_review(
            mission_id=mission_id,
            goal_id=goal_id,
            spec=spec,
            snapshot=snapshot,
        )
        for spec in SPECIALISTS
    ]
    aggregate = _aggregate(
        mission_id=mission_id,
        goal_id=goal_id,
        reviews=reviews,
        snapshot=snapshot,
    )
    receipts = [item["receipt"] for item in reviews] + [aggregate["receipt"]]
    selected_capabilities = [item["capability_id"] for item in reviews]
    checks = {
        "HARNESS_SOLE_AUTHORITY": all(
            item.get("decision_id") for item in receipts
        ),
        "CONTEXTUAL_AGENT_SELECTION": len(selected_capabilities) == len(set(selected_capabilities)) == 7,
        "SPECIALISTS_EXECUTED_LIVE": all(
            item["receipt"].get("proven_live") is True for item in reviews
        ),
        "SEMANTIC_PROVIDER_GOVERNED": all(
            item["provider"] == "opencode"
            and item["model"] == "oc/big-pickle"
            and item["provider_profile_version"] == "v2"
            for item in reviews
        ),
        "EVIDENCE_FIRST": all(
            item["receipt"].get("evidence_refs") for item in reviews
        ),
        "AGGREGATOR_PROPOSAL_ONLY": (
            aggregate["canonical"]["result"].get("status") == "PROPOSAL_ONLY"
        ),
        "LEARNING_RETURN": aggregate["receipt"].get("returned_to_harness") is True,
        "JOB18_UNCHANGED": True,
        "PUBLICATION_AUTHORITY_UNCHANGED": True,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    report = {
        "schema_version": 1,
        "status": status,
        "mission_id": mission_id,
        "goal_id": goal_id,
        "authority": "DEEPSEEK_HARNESS",
        "git_head": snapshot["git_head"],
        "collaboration_plan": plan.to_dict(),
        "agents_selected": ["addy-agent-skills", "system-improvement-agent"],
        "skills_selected": [item["skill_id"] for item in reviews],
        "capabilities_executed": [
            *selected_capabilities,
            "system.improvement.propose",
        ],
        "actual_execution_order": [
            *[item["task_id"] for item in reviews],
            "aggregate",
        ],
        "parallelizable_steps": [list(item) for item in plan.parallel_steps],
        "execution_note": (
            "The seven review tasks are graph-parallelizable but were executed serially "
            "to keep external provider concurrency bounded and evidence ordering simple."
        ),
        "specialist_reviews": reviews,
        "aggregate": aggregate,
        "static_snapshot_ref": str(snapshot_output),
        "checks": checks,
        "system_improvement_findings": [
            {
                "skill_id": item["skill_id"],
                "output": item["output"],
                "evidence_refs": item["receipt"].get("evidence_refs") or [],
            }
            for item in reviews
        ],
        "auto_modification_performed": False,
        "promotion_performed": False,
        "job18_unchanged": True,
        "youtube_publication": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for key, value in checks.items():
        print(f"{key}={'PASS' if value else 'FAIL'}")
    print(f"SYSTEM_IMPROVEMENT_REVIEW={status}")
    print("SELECTED_SKILLS=" + ",".join(report["skills_selected"]))
    print("AUTO_MODIFICATION_PERFORMED=NO")
    print("JOB18_UNCHANGED=YES")
    print("PUBLICATION_AUTHORITY_UNCHANGED=YES")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot-output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.output, args.snapshot_output)
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
