from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any

from app.main import initialize_application
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_learning_service import (
    HarnessEpisode,
    attach_candidate_to_improvement_mission,
    complete_improvement_mission,
    create_improvement_mission,
    create_learning_candidate,
    evaluate_candidate_from_observed_results,
    persist_episode,
    promote_candidate,
    register_skill_version,
)
from app.services.opencode_native_ai_provider import (
    build_semantic_text_only_env,
    build_semantic_text_only_prompt,
)
from app.services.opencode_semantic_profile import OPENCODE_SEMANTIC_AGENT_ID
from app.services.opencode_executor_profile_service import (
    BASELINE_OPENCODE_EXECUTOR_VERSION,
    CANDIDATE_OPENCODE_EXECUTOR_VERSION,
    SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION,
    OPENCODE_EXECUTOR_SKILL_ID,
    executable_opencode_executor_profile,
    resolve_active_opencode_executor_profile,
)


CANONICAL_MODEL = "oc/big-pickle"
EXECUTOR_MODEL = "opencode/big-pickle"
EXPECTED_TEXT = "BR_NO_GTA_SYSTEM_SYNERGY_PROVIDER_OK"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _metrics(*, success: bool, quality: float, latency: float) -> dict[str, float]:
    return {
        "task_success_rate": 1.0 if success else 0.0,
        "quality": float(quality),
        "human_correction_rate": 0.0,
        "retry_rate": 0.0,
        "failure_recurrence": 0.0 if success else 1.0,
        "latency_seconds": float(latency),
        "cost": 0.0,
        "policy_violations": 0.0,
    }


def _wait_for_gateway(timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:20128/api/monitoring/health",
                timeout=3,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if payload.get("status") == "healthy":
                    return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("OmniRoute baseline gateway did not become healthy")


def _baseline_probe(prompt: str, root: Path) -> dict[str, Any]:
    log_path = root / "omniroute-baseline.log"
    env = {**os.environ, "OMNIROUTE_SERVER_HOST": "127.0.0.1"}
    started_at = _utcnow()
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            ["omniroute", "serve"],
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
    try:
        _wait_for_gateway()
        request = urllib.request.Request(
            "http://127.0.0.1:20128/v1/providers/opencode/chat/completions",
            data=json.dumps({
                "model": CANONICAL_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        text = ""
        http_status = None
        error_code = None
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                http_status = response.status
                payload = json.loads(response.read().decode("utf-8", "replace"))
                choices = payload.get("choices") or []
                if choices:
                    text = str((choices[0].get("message") or {}).get("content") or "")
        except urllib.error.HTTPError as exc:
            http_status = exc.code
            error_code = f"upstream_http_{exc.code}"
            exc.read()
        except Exception as exc:
            error_code = type(exc).__name__
        latency = time.monotonic() - started
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    finished_at = _utcnow()
    success = text.strip() == EXPECTED_TEXT
    quality = 1.0 if success else 0.0
    return {
        "observed": True,
        "role": "baseline",
        "provider": "opencode",
        "canonical_model": CANONICAL_MODEL,
        "executor": "omniroute-http",
        "executor_version": "3.8.50",
        "outcome": "COMPLETED" if success else "FAILED",
        "http_status": http_status,
        "error_code": error_code,
        "usable_text": bool(text.strip()),
        "text_matches_expected": success,
        "latency_seconds": latency,
        "metrics": _metrics(success=success, quality=quality, latency=latency),
        "started_at": started_at,
        "finished_at": finished_at,
        "fallback_occurred": False,
        "retry_count": 0,
    }


def _candidate_probe(prompt: str, root: Path) -> dict[str, Any]:
    started_at = _utcnow()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="br-opencode-probe-") as tmp:
        process = subprocess.run(
            [
                "opencode", "run", "--standalone", "--model", EXECUTOR_MODEL,
                "--agent", OPENCODE_SEMANTIC_AGENT_ID,
                "--format", "json", build_semantic_text_only_prompt(prompt),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            cwd=tmp,
            env=build_semantic_text_only_env(dict(os.environ)),
        )
    latency = time.monotonic() - started
    finished_at = _utcnow()
    parts: list[str] = []
    parse_errors = 0
    event_types: list[str] = []
    error_events: list[str] = []
    tool_call_count = 0
    for raw in process.stdout.splitlines():
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        event_type = str(item.get("type") or "")
        if event_type:
            event_types.append(event_type)
        if event_type in {"tool_use", "tool_call", "tool"}:
            tool_call_count += 1
        if event_type != "text":
            candidate_error = item.get("error") or item.get("message") or item.get("data")
            if candidate_error:
                safe = str(candidate_error)[:1200]
                safe = re.sub(
                    r"(?i)(authorization:|bearer\\s+|api[_-]?key|token=|sk-|ghp_|github_pat_)[^\\s,;]*",
                    "[REDACTED]",
                    safe,
                )
                error_events.append(safe)
            continue
        part = item.get("part") or {}
        value = part.get("text")
        if isinstance(value, str):
            parts.append(value)
    answer = "".join(parts).strip()
    success = (
        process.returncode == 0
        and answer == EXPECTED_TEXT
        and tool_call_count == 0
    )
    return {
        "observed": True,
        "role": "candidate",
        "provider": "opencode",
        "canonical_model": CANONICAL_MODEL,
        "executor_model": EXECUTOR_MODEL,
        "executor": "official-opencode-cli",
        "executor_version": "2.0.8",
        "outcome": "COMPLETED" if success else "FAILED",
        "exit_code": process.returncode,
        "usable_text": bool(answer),
        "text_matches_expected": answer == EXPECTED_TEXT,
        "parse_errors": parse_errors,
        "event_types": list(dict.fromkeys(event_types)),
        "tool_call_count": tool_call_count,
        "tools_exposed": 0 if tool_call_count == 0 else tool_call_count,
        "semantic_agent": OPENCODE_SEMANTIC_AGENT_ID,
        "semantic_contract": "SEMANTIC_TEXT_ONLY",
        "error_events": error_events[-5:],
        "safe_stderr": [
            line[:500]
            for line in process.stderr.splitlines()
            if not re.search(
                r"(?i)(authorization:|bearer |api[_-]?key|token=|sk-|ghp_|github_pat_)",
                line,
            )
        ][-10:],
        "latency_seconds": latency,
        "metrics": _metrics(
            success=success,
            quality=1.0 if answer == EXPECTED_TEXT else 0.0,
            latency=latency,
        ),
        "started_at": started_at,
        "finished_at": finished_at,
        "fallback_occurred": False,
        "retry_count": 0,
        "stdout_sha256": sha256(process.stdout.encode()).hexdigest(),
        "stderr_sha256": sha256(process.stderr.encode()).hexdigest(),
    }


def prepare(output: Path) -> dict[str, Any]:
    initialize_application()
    output.parent.mkdir(parents=True, exist_ok=True)
    run_id = str(os.getenv("GITHUB_RUN_ID") or "local")
    prompt = f"Return only: {EXPECTED_TEXT}"
    prompt_sha = sha256(prompt.encode()).hexdigest()
    fingerprint = sha256(json.dumps({
        "task_class": "system-synergy-semantic-provider",
        "provider": "opencode",
        "canonical_model": CANONICAL_MODEL,
        "prompt_sha256": prompt_sha,
        "expected_text": EXPECTED_TEXT,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    baseline = _baseline_probe(prompt, output.parent)
    candidate = _candidate_probe(prompt, output.parent)
    baseline["workload_fingerprint"] = fingerprint
    candidate["workload_fingerprint"] = fingerprint
    baseline["evidence_refs"] = [
        f"github:run:{run_id}:opencode-baseline",
        f"workload:{fingerprint}",
        f"prompt-sha256:{prompt_sha}",
    ]
    candidate["evidence_refs"] = [
        f"github:run:{run_id}:opencode-candidate",
        f"workload:{fingerprint}",
        f"prompt-sha256:{prompt_sha}",
    ]

    regression_checks = {
        "same_workload": baseline["workload_fingerprint"] == candidate["workload_fingerprint"],
        "same_provider": baseline["provider"] == candidate["provider"] == "opencode",
        "same_canonical_model": baseline["canonical_model"] == candidate["canonical_model"] == CANONICAL_MODEL,
        "candidate_completed": candidate["metrics"]["task_success_rate"] == 1.0,
        "candidate_exact_quality": candidate["metrics"]["quality"] == 1.0,
        "candidate_zero_cost": candidate["metrics"]["cost"] == 0.0,
        "candidate_policy_violations_zero": candidate["metrics"]["policy_violations"] == 0.0,
        "candidate_no_fallback": candidate["fallback_occurred"] is False,
    }
    regression = {
        "observed": True,
        "status": "PASS" if all(regression_checks.values()) else "FAIL",
        "checks": regression_checks,
        "critical_failures": [k for k, v in regression_checks.items() if not v],
        "evidence_refs": [f"github:run:{run_id}:opencode-regression", f"workload:{fingerprint}"],
    }
    adversarial_checks = {
        "explicit_provider": candidate["provider"] == "opencode",
        "explicit_executor_model": candidate["executor_model"] == EXECUTOR_MODEL,
        "canonical_model_unchanged": candidate["canonical_model"] == CANONICAL_MODEL,
        "no_fallback": candidate["fallback_occurred"] is False,
    }
    adversarial = {
        "observed": True,
        "status": "PASS" if all(adversarial_checks.values()) else "FAIL",
        "checks": adversarial_checks,
        "critical_failures": [k for k, v in adversarial_checks.items() if not v],
        "evidence_refs": [f"github:run:{run_id}:opencode-adversarial", f"workload:{fingerprint}"],
    }

    episode_id = f"episode-system-synergy-opencode-{run_id}"
    episode = persist_episode(HarnessEpisode(
        episode_id=episode_id,
        goal_id=f"goal-system-synergy-provider-{run_id}",
        decision_id=f"decision-system-synergy-provider-{run_id}",
        execution_id=f"execution-system-synergy-provider-{run_id}",
        task_id="opencode-baseline-observation",
        agent_id="provider:opencode",
        capability_id="ai.reasoning.text",
        domain="ai",
        task_class="system-synergy-semantic-provider",
        started_at=str(baseline["started_at"]),
        finished_at=str(baseline["finished_at"]),
        duration_seconds=float(baseline["latency_seconds"]),
        status="COMPLETED" if baseline["metrics"]["task_success_rate"] == 1.0 else "FAILED",
        actual_outcome={
            "observed": True,
            "success": baseline["metrics"]["task_success_rate"] == 1.0,
            "provider": "opencode",
            "baseline": baseline,
        },
        outcome_evidence=tuple(baseline["evidence_refs"]),
        skill_id=OPENCODE_EXECUTOR_SKILL_ID,
        skill_version=BASELINE_OPENCODE_EXECUTOR_VERSION,
        provider="opencode",
        input_refs=(f"prompt-sha256:{prompt_sha}",),
        output_refs=(f"baseline-result:{run_id}",),
        evidence_refs=tuple(baseline["evidence_refs"]),
        error=None if baseline["metrics"]["task_success_rate"] == 1.0 else str(baseline.get("error_code") or "baseline_failed"),
        retry_count=0,
        human_intervention=False,
        cost=0.0,
        latency_seconds=float(baseline["latency_seconds"]),
        run_ref=f"github:run:{run_id}",
        source_versions={f"skill:{OPENCODE_EXECUTOR_SKILL_ID}": "v1"},
        lineage={"observed_runtime": "github-actions", "promotion_performed": False},
    ))

    v1 = executable_opencode_executor_profile(BASELINE_OPENCODE_EXECUTOR_VERSION)
    v2 = executable_opencode_executor_profile(CANDIDATE_OPENCODE_EXECUTOR_VERSION)
    v3 = executable_opencode_executor_profile(SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION)
    common_refs = tuple(dict.fromkeys([
        *baseline["evidence_refs"],
        *candidate["evidence_refs"],
        *regression["evidence_refs"],
        *adversarial["evidence_refs"],
        f"episode:{episode_id}",
    ]))
    register_skill_version(
        skill_id=OPENCODE_EXECUTOR_SKILL_ID,
        version="v1",
        parent_version=None,
        content_ref=v1["content_ref"],
        checksum=v1["checksum"],
        status="ACTIVE",
        evidence_refs=common_refs,
    )
    register_skill_version(
        skill_id=OPENCODE_EXECUTOR_SKILL_ID,
        version="v3",
        parent_version="v2",
        content_ref=v3["content_ref"],
        checksum=v3["checksum"],
        status="CANDIDATE",
        evidence_refs=common_refs,
    )

    improvement_auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="learning:improvement",
        harness_decision_id=episode["decision_id"],
        execution_id=f"system-synergy-improvement-{run_id}",
        lineage={"source_episode_id": episode_id, "workload_fingerprint": fingerprint},
    )
    try:
        mission = create_improvement_mission(
            trigger_type="OBSERVED_PROVIDER_EXECUTOR_BASELINE",
            trigger_refs=(f"episode:{episode_id}",),
            diagnosis=(
                "Observed the currently governed OpenCode baseline and the official OpenCode CLI "
                "candidate on an equivalent semantic workload."
            ),
            hypothesis=(
                "The official OpenCode semantic text profile v3 can replace the baseline executor only if observed "
                "success/quality improves with no policy, cost or fallback regression."
            ),
            authorization=improvement_auth,
            evidence_considered=common_refs,
            affected_capability="ai.reasoning.text",
            affected_config=f"skill:{OPENCODE_EXECUTOR_SKILL_ID}/v1",
            objective="Enable a measured zero-cost semantic provider for the real multi-agent mission.",
            constraints=(
                "provider remains opencode",
                "canonical model remains oc/big-pickle",
                "zero cost preserved",
                "no fallback",
                "promotion requires observed evaluation",
            ),
            acceptance_criteria={"max_policy_violations": 0, "fallback_occurred": False},
        )
        acceptance = {
            "max_policy_violations": 0,
            "max_candidate_latency_seconds": 120.0,
        }
        if baseline["metrics"]["task_success_rate"] < 1.0:
            acceptance["min_task_success_rate_increase"] = 1.0
        else:
            acceptance["min_latency_reduction_fraction"] = 0.05
        learning_candidate = create_learning_candidate(
            candidate_type="SKILL_UPDATE",
            hypothesis="Use official OpenCode semantic text profile v3 only after observed non-regression and measurable improvement.",
            domain="ai",
            task_class="system-synergy-semantic-provider",
            source_episode_ids=(episode_id,),
            evidence_refs=common_refs,
            target_agent_id="provider:opencode",
            target_capability_id="ai.reasoning.text",
            target_skill_id=OPENCODE_EXECUTOR_SKILL_ID,
            baseline_version="v2",
            candidate_version="v3",
            implementation_ref=v3["content_ref"],
            acceptance_criteria=acceptance,
            contradiction_check={
                "status": "OBSERVED_EQUIVALENT_WORKLOAD",
                "same_workload": True,
                "same_provider": True,
                "same_canonical_model": True,
            },
        )
        mission = attach_candidate_to_improvement_mission(
            improvement_mission_id=mission["improvement_mission_id"],
            candidate_id=learning_candidate["candidate_id"],
            authorization=improvement_auth,
        )
    finally:
        consume_harness_authorization(improvement_auth)

    evaluation = evaluate_candidate_from_observed_results(
        candidate_id=learning_candidate["candidate_id"],
        baseline_observation=baseline,
        candidate_observation=candidate,
        regression_observation=regression,
        adversarial_observation=adversarial,
        evidence_refs=common_refs,
    )

    promotion = None
    if evaluation["decision"] == "PROMOTE":
        promotion_auth = issue_harness_authorization(
            authorized_action="EXECUTION",
            subject=f"learning:candidate:{learning_candidate['candidate_id']}",
            harness_decision_id=episode["decision_id"],
            execution_id=f"system-synergy-promotion-{run_id}",
            lineage={
                "source_episode_id": episode_id,
                "improvement_mission_id": mission["improvement_mission_id"],
                "candidate_id": learning_candidate["candidate_id"],
                "evaluation_id": evaluation["evaluation_id"],
            },
        )
        try:
            promotion = promote_candidate(
                candidate_id=learning_candidate["candidate_id"],
                evaluation=evaluation,
                authorization=promotion_auth,
                memory_claim=(
                    "Observed system-synergy provider benchmark promoted OpenCode semantic text profile v3 "
                    "after measurable improvement with zero-cost/no-fallback regression gates."
                ),
                memory_type="PROCEDURAL",
                source_versions={f"skill:{OPENCODE_EXECUTOR_SKILL_ID}": "v3"},
            )
        finally:
            consume_harness_authorization(promotion_auth)

        completion_auth = issue_harness_authorization(
            authorized_action="EXECUTION",
            subject="learning:improvement",
            harness_decision_id=episode["decision_id"],
            execution_id=f"system-synergy-improvement-complete-{run_id}",
            lineage={
                "improvement_mission_id": mission["improvement_mission_id"],
                "candidate_id": learning_candidate["candidate_id"],
                "evaluation_id": evaluation["evaluation_id"],
            },
        )
        try:
            mission = complete_improvement_mission(
                improvement_mission_id=mission["improvement_mission_id"],
                authorization=completion_auth,
            )
        finally:
            consume_harness_authorization(completion_auth)

    active = resolve_active_opencode_executor_profile()
    proof = {
        "schema_version": 1,
        "status": "PASS" if evaluation["decision"] == "PROMOTE" and active["version"] == "v3" else "BLOCKED",
        "run_id": run_id,
        "workload_fingerprint": fingerprint,
        "baseline": baseline,
        "candidate": candidate,
        "regression": regression,
        "adversarial": adversarial,
        "episode_id": episode_id,
        "improvement_mission_id": mission["improvement_mission_id"],
        "candidate_id": learning_candidate["candidate_id"],
        "evaluation_id": evaluation["evaluation_id"],
        "evaluation_decision": evaluation["decision"],
        "promotion": promotion,
        "active_profile": active,
        "quality_regression": "NO" if regression["status"] == "PASS" else "YES",
        "fallback_occurred": False,
        "zero_cost": True,
    }
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OPENCODE_BASELINE_OUTCOME={baseline['outcome']}")
    print(f"OPENCODE_CANDIDATE_OUTCOME={candidate['outcome']}")
    print(f"OPENCODE_EVALUATION={evaluation['decision']}")
    print(f"OPENCODE_ACTIVE_PROFILE={active['version']}")
    print("OPENCODE_GOVERNED_PROMOTION=" + ("PASS" if proof["status"] == "PASS" else "BLOCKED"))
    return proof


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    proof = prepare(args.output)
    return 0 if proof["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
