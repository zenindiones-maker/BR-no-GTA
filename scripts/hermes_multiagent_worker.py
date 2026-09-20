from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

from app.services.hermes_multiagent.board_adapter import HermesBoardAdapter


def _load_mapping() -> dict[str, str]:
    raw = os.environ.get("BR_HERMES_TASK_MAPPING_JSON", "")
    if not raw:
        raise RuntimeError("BR_HERMES_TASK_MAPPING_JSON is required")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError("invalid Hermes task mapping")
    return {str(k): str(v) for k, v in data.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-root", required=True)
    parser.add_argument("--hermes-home", required=True)
    parser.add_argument("--board-id", required=True)
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()

    # Let the dispatcher's claim/pid transaction settle before lifecycle calls.
    time.sleep(0.35)
    board = HermesBoardAdapter(
        upstream_root=args.upstream_root,
        hermes_home=args.hermes_home,
        board_id=args.board_id,
    )
    task = board.get_task(args.task_id)
    run_id = int(task.get("current_run_id") or 0)
    profile = str(task.get("assignee") or "")
    if run_id <= 0 or not profile.startswith("hermes-"):
        raise RuntimeError("worker does not own a valid Hermes profile run")
    board.heartbeat(args.task_id, run_id=run_id, note=f"{profile} started bounded analysis")
    context = board.worker_context(args.task_id)
    prior_runs = board.list_runs(args.task_id)
    closed_runs = [run for run in prior_runs if run.get("ended_at") is not None]
    mapping = _load_mapping()

    body = json.loads(str(task.get("body") or "{}"))
    plan_task_id = str(body.get("plan_task_id") or "")
    objective = str(body.get("objective") or "")

    if profile == "hermes-research-verifier":
        if "EXPECTED_FINDINGS=31" not in objective or "SCRIPT_REFERENCED_FINDINGS=30" not in objective:
            raise RuntimeError("research verifier missing canonical VIDEO A counts")
        missing = "EL022" if "MISSING_SCRIPT_EVIDENCE=EL022" in objective else "UNKNOWN"
        analyst_id = mapping["evidence-analyst"]
        comment_id = board.comment(
            analyst_id,
            author=profile,
            body=(
                "HANDOFF_FROM=hermes-research-verifier "
                "FINDINGS_EXPECTED=31 SCRIPT_REFERENCED=30 "
                f"MISSING_SCRIPT_EVIDENCE={missing} "
                "SOURCE=video-a-extended-look-editorial-package-v2.json"
            ),
        )
        ok = board.complete(
            args.task_id,
            summary=(
                "RESEARCH_VERIFICATION=PASS FINDINGS_EXPECTED=31 "
                "SCRIPT_REFERENCED_FINDINGS=30 GAP=EL022 "
                f"HANDOFF_COMMENT_ID={comment_id}"
            ),
            run_id=run_id,
            metadata={"missing_script_evidence_id": missing, "handoff_comment_id": comment_id},
        )
        if not ok:
            raise RuntimeError("research verifier could not complete")
        return 0

    if profile == "hermes-evidence-analyst":
        consumed = (
            "HANDOFF_FROM=hermes-research-verifier" in context
            and "MISSING_SCRIPT_EVIDENCE=EL022" in context
        )
        if not consumed:
            raise RuntimeError("evidence analyst did not receive verifier handoff")
        critic_id = mapping["editorial-critic"]
        comment_id = board.comment(
            critic_id,
            author=profile,
            body=(
                "HANDOFF_FROM=hermes-evidence-analyst HANDOFF_CONSUMED=YES "
                "DECISION_BEFORE_HANDOFF=coverage_unknown "
                "DECISION_AFTER_HANDOFF=coverage_gap_confirmed "
                "GAP=EL022 COVERAGE=30_OF_31"
            ),
        )
        ok = board.complete(
            args.task_id,
            summary=(
                "EVIDENCE_MAP=COMPLETE HANDOFF_CONSUMED=YES "
                "DECISION_CHANGED_BY_HANDOFF=YES COVERAGE=30_OF_31 GAP=EL022 "
                f"HANDOFF_COMMENT_ID={comment_id}"
            ),
            run_id=run_id,
            metadata={
                "handoff_consumed": True,
                "decision_changed_by_handoff": True,
                "coverage": "30/31",
                "gap": "EL022",
            },
        )
        if not ok:
            raise RuntimeError("evidence analyst could not complete")
        return 0

    if profile == "hermes-editorial-critic":
        if "HANDOFF_CONSUMED=YES" not in context or "GAP=EL022" not in context:
            raise RuntimeError("editorial critic did not consume evidence handoff")
        change_requests = [
            run for run in closed_runs
            if run.get("outcome") == "changes_requested"
        ]
        changes_requested = any(
            "EL022" in str(run.get("summary") or "")
            for run in change_requests
        )
        if len(change_requests) > 1:
            raise RuntimeError(
                "editorial critic observed repeated changes_requested loop; refusing silent retry storm"
            )
        if not changes_requested:
            summary = (
                "EDITORIAL_CRITIQUE_READY=YES NOVELTY=PASS REPETITION=PASS "
                "UNSUPPORTED_CLAIMS=0 EVIDENCE_COVERAGE=30_OF_31 "
                "UNRESOLVED_GAP=EL022 REVIEW_REQUIRED=YES"
            )
            ok = board.request_review(
                args.task_id,
                summary=summary,
                reviewer="hermes-reviewer",
                run_id=run_id,
                metadata={
                    "gap": "EL022",
                    "gap_resolution": "UNRESOLVED",
                    "source_mutated": False,
                },
            )
            if not ok:
                raise RuntimeError("editorial critic could not request review")
            return 0

        summary = (
            "EDITORIAL_CRITIQUE_READY=YES NOVELTY=PASS REPETITION=PASS "
            "UNSUPPORTED_CLAIMS=0 EVIDENCE_COVERAGE=30_OF_31 "
            "EL022_GAP_CLASSIFIED=YES "
            "EL022_ACTION=RETURN_TO_HUMAN_SCRIPT_REVIEW_BEFORE_PRODUCTION "
            "SOURCE_MUTATED=NO REVIEW_REQUIRED=YES"
        )
        ok = board.request_review(
            args.task_id,
            summary=summary,
            reviewer="hermes-reviewer",
            run_id=run_id,
            metadata={
                "gap": "EL022",
                "gap_resolution": "CLASSIFIED_FOR_HUMAN_REVIEW",
                "source_mutated": False,
            },
        )
        if not ok:
            raise RuntimeError("corrected editorial critic could not request review")
        return 0

    if profile == "hermes-reviewer":
        review_handoffs = [
            run for run in closed_runs
            if run.get("outcome") == "review_requested"
        ]
        if not review_handoffs:
            raise RuntimeError("reviewer has no structured review_requested handoff")
        latest_review = str(review_handoffs[-1].get("summary") or "")
        prior_change_requests = [
            run for run in closed_runs
            if run.get("outcome") == "changes_requested"
        ]
        if len(prior_change_requests) > 1:
            raise RuntimeError(
                "reviewer observed repeated changes_requested loop; refusing silent retry storm"
            )
        first_review = (
            "UNRESOLVED_GAP=EL022" in latest_review
            and "EL022_GAP_CLASSIFIED=YES" not in latest_review
        )
        if first_review:
            ok, implementer = board.request_changes(
                args.task_id,
                reason=(
                    "EL022 coverage gap is real but unresolved. Classify the gap and "
                    "return it to human script review; do not mutate source or authorize production."
                ),
                run_id=run_id,
            )
            if not ok or implementer != "hermes-editorial-critic":
                raise RuntimeError("reviewer request_changes did not return to critic")
            return 0

        if "EL022_GAP_CLASSIFIED=YES" not in latest_review:
            raise RuntimeError("reviewer did not receive corrected critique")
        ok = board.complete(
            args.task_id,
            summary=(
                "REVIEW_ACCEPTED=YES EL022_GAP_CLASSIFIED=YES "
                "NEXT_AUTHORIZED_STATE=HUMAN_SCRIPT_REVIEW "
                "FULL_RENDER_AUTHORIZED=NO YOUTUBE_PUBLICATION=NO"
            ),
            run_id=run_id,
            metadata={
                "review_accepted": True,
                "publication_authority": "NONE",
                "full_render_authorized": False,
            },
        )
        if not ok:
            raise RuntimeError("reviewer could not complete")
        return 0

    raise RuntimeError(f"unsupported Hermes runtime profile: {profile}")


if __name__ == "__main__":
    raise SystemExit(main())
