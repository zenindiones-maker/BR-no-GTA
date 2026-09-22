from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _episodes(report: dict[str, Any]) -> set[str]:
    canonical = dict(report.get("hermes_canonical_result") or {})
    result = dict(canonical.get("result") or {})
    return {
        str(item)
        for item in (result.get("harness_episode_ids") or ())
        if str(item).strip()
    }


def _task_signature(plan: dict[str, Any]) -> tuple[tuple[str, str, str], ...]:
    tasks = list(
        (plan.get("mission_plan") or {})
        .get("collaboration_plan", {})
        .get("tasks", [])
    )
    return tuple(
        (
            str(item.get("task_class") or ""),
            str(item.get("capability_id") or ""),
            str(
                item.get("selected_agent_id")
                or item.get("selected_skill_id")
                or ""
            ),
        )
        for item in tasks
    )


def _selection_by_task(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("task_id") or ""): item
        for item in (
            (plan.get("selection") or {}).get("selections") or ()
        )
        if str(item.get("task_id") or "")
    }


def _audit_counts(report: dict[str, Any]) -> dict[str, int]:
    audit = list(report.get("audit") or ())
    retry_count = sum(
        1 for item in audit
        if str(item.get("event") or item.get("event_type") or "").upper()
        in {"RETRY", "TASK_RETRY", "RETRYING"}
    )
    reused_count = sum(
        1 for item in audit
        if bool(item.get("reused"))
        or str(item.get("event") or "").upper() in {
            "RESULT_REUSED",
            "IDEMPOTENT_REUSE",
        }
    )
    return {
        "audit_events": len(audit),
        "retry_count": retry_count,
        "reused_count": reused_count,
        "handoff_count": len(report.get("handoffs") or ()),
        "review_count": len(report.get("integration_gates") or ()),
    }


def compare(
    *,
    first_plan: dict[str, Any],
    second_plan: dict[str, Any],
    first_report: dict[str, Any],
    second_report: dict[str, Any],
) -> dict[str, Any]:
    first_episodes = _episodes(first_report)
    second_episodes = _episodes(second_report)
    if not first_episodes:
        raise AssertionError("first real execution produced no HarnessEpisode ids")
    if not second_episodes:
        raise AssertionError("second real execution produced no HarnessEpisode ids")
    if first_episodes & second_episodes:
        raise AssertionError("second execution reused HarnessEpisode identity")

    first_selection = _selection_by_task(first_plan)
    second_selection = _selection_by_task(second_plan)
    shared_tasks = sorted(set(first_selection) & set(second_selection))
    competence_deltas: list[dict[str, Any]] = []

    for task_id in shared_tasks:
        before = first_selection[task_id]
        after = second_selection[task_id]
        before_candidates = {
            str(item.get("capability_id")): item
            for item in (before.get("top_candidates") or ())
        }
        after_candidates = {
            str(item.get("capability_id")): item
            for item in (after.get("top_candidates") or ())
        }
        for capability_id in sorted(
            set(before_candidates) & set(after_candidates)
        ):
            old = before_candidates[capability_id]
            new = after_candidates[capability_id]
            old_n = int(old.get("sample_size") or 0)
            new_n = int(new.get("sample_size") or 0)
            old_conf = old.get("confidence_adjusted_success")
            new_conf = new.get("confidence_adjusted_success")
            old_comp = float(
                (old.get("score_components") or {}).get("competence") or 0.0
            )
            new_comp = float(
                (new.get("score_components") or {}).get("competence") or 0.0
            )
            if new_n > old_n or new_comp != old_comp or new_conf != old_conf:
                competence_deltas.append({
                    "task_id": task_id,
                    "capability_id": capability_id,
                    "sample_size_before": old_n,
                    "sample_size_after": new_n,
                    "competence_component_before": old_comp,
                    "competence_component_after": new_comp,
                    "confidence_adjusted_success_before": old_conf,
                    "confidence_adjusted_success_after": new_conf,
                })

    first_sig = _task_signature(first_plan)
    second_sig = _task_signature(second_plan)
    first_route = dict(first_plan.get("route") or {})
    second_route = dict(second_plan.get("route") or {})
    first_audit = _audit_counts(first_report)
    second_audit = _audit_counts(second_report)

    first_refs = {
        str(ref)
        for task in (
            (first_plan.get("mission_plan") or {})
            .get("collaboration_plan", {})
            .get("tasks", [])
        )
        for ref in (task.get("input_refs") or ())
    }
    second_refs = {
        str(ref)
        for task in (
            (second_plan.get("mission_plan") or {})
            .get("collaboration_plan", {})
            .get("tasks", [])
        )
        for ref in (task.get("input_refs") or ())
    }
    new_reuse_refs = sorted(second_refs - first_refs)

    second_planning = dict(
        (second_plan.get("mission_plan") or {}).get("planning_evidence") or {}
    )
    known_bad_paths = list(
        (second_plan.get("mission_plan") or {}).get(
            "known_bad_paths_avoided"
        ) or ()
    )
    memory_influences = bool(
        (second_plan.get("mission_plan") or {}).get(
            "memory_influences_strategy"
        )
    )
    competence_influences = bool(
        (second_plan.get("selection") or {}).get(
            "competence_influenced_selection"
        )
    )
    strategy_changes = {
        "task_or_capability_signature_changed": first_sig != second_sig,
        "topology_changed": (
            first_route.get("runtime") != second_route.get("runtime")
        ),
        "team_size_changed": (
            int(first_plan.get("unique_team_size") or 0)
            != int(second_plan.get("unique_team_size") or 0)
        ),
        "new_artifact_or_evidence_reuse": bool(new_reuse_refs),
        "known_bad_path_avoided": bool(known_bad_paths),
        "retry_count_reduced": (
            second_audit["retry_count"] < first_audit["retry_count"]
        ),
        "idempotent_reuse_increased": (
            second_audit["reused_count"] > first_audit["reused_count"]
        ),
        "competence_ranking_changed_with_new_sample": any(
            item["sample_size_after"] > item["sample_size_before"]
            and (
                item["competence_component_after"]
                != item["competence_component_before"]
                or item["confidence_adjusted_success_after"]
                != item["confidence_adjusted_success_before"]
            )
            for item in competence_deltas
        ),
    }
    changed = any(strategy_changes.values())
    learning_read = (
        int(second_plan.get("learning_source_run_id") or 0) > 0
        and int(second_plan.get("competence_records_present") or 0) > 0
    )
    learning_influenced = (
        competence_influences
        or memory_influences
        or bool(known_bad_paths)
        or bool(new_reuse_refs)
    )
    causal = (
        learning_read
        and bool(competence_deltas)
        and learning_influenced
        and changed
    )

    return {
        "schema": "delegation-plane-learning-compare/v1",
        "status": "PASS" if causal else "FAIL",
        "first_harness_episode_ids": sorted(first_episodes),
        "second_harness_episode_ids": sorted(second_episodes),
        "competence_deltas": competence_deltas,
        "strategy_changes": strategy_changes,
        "first_audit_metrics": first_audit,
        "second_audit_metrics": second_audit,
        "new_reuse_refs": new_reuse_refs,
        "known_bad_paths_avoided_second": known_bad_paths,
        "second_planning_selection_count": len(
            second_planning.get("selection") or ()
        ),
        "LEARNING_CAPTURED_FROM_REAL_EXECUTION": (
            "PASS" if first_episodes else "FAIL"
        ),
        "COMPETENCE_GRAPH_UPDATED": (
            "PASS"
            if any(
                item["sample_size_after"] > item["sample_size_before"]
                for item in competence_deltas
            )
            else "FAIL"
        ),
        "NEXT_SIMILAR_EXECUTION_READS_LEARNING": (
            "PASS" if learning_read else "FAIL"
        ),
        "LEARNING_INFLUENCED_SELECTION_OR_STRATEGY": (
            "PASS" if learning_influenced else "FAIL"
        ),
        "NEXT_EXECUTION_CHANGED_BY_LEARNING": (
            "PASS" if causal else "FAIL"
        ),
        "SECOND_LEARNING_PLANE": "NO",
        "CI_REAL_TELEGRAM_EGRESS": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-plan", required=True)
    parser.add_argument("--second-plan", required=True)
    parser.add_argument("--first-report", required=True)
    parser.add_argument("--second-report", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = compare(
        first_plan=_load(args.first_plan),
        second_plan=_load(args.second_plan),
        first_report=_load(args.first_report),
        second_report=_load(args.second_report),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    for key in (
        "LEARNING_CAPTURED_FROM_REAL_EXECUTION",
        "COMPETENCE_GRAPH_UPDATED",
        "NEXT_SIMILAR_EXECUTION_READS_LEARNING",
        "LEARNING_INFLUENCED_SELECTION_OR_STRATEGY",
        "NEXT_EXECUTION_CHANGED_BY_LEARNING",
    ):
        print(f"{key}={result[key]}")
    print("SECOND_LEARNING_PLANE=NO")
    print("CI_REAL_TELEGRAM_EGRESS=0")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
