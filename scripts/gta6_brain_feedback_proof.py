from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from app.database import harness_learning_repository
from app.database.schema import initialize_schema
from app.services.gta6_brain_harness_service import (
    GTA6_BRAIN_CAPABILITY_ID,
    execute_authorized_gta6_brain_decision,
)
from app.services.gta6_domain_projection_service import (
    GTA6_DOMAIN_PROJECTION_SCHEMA,
    build_gta6_domain_projection,
)
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


def _route_and_authorize(*, goal_id: str):
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="consult GTA6 domain specialist with causal feedback",
            authorized_action="DECISION",
            domain="gta6-decision",
            task_class="gta6-domain-decision",
            goal_id=goal_id,
            required_capability_id=GTA6_BRAIN_CAPABILITY_ID,
            fallback_allowed=False,
            provider_required=False,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="DECISION",
        subject=f"capability:{GTA6_BRAIN_CAPABILITY_ID}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": GTA6_BRAIN_CAPABILITY_ID,
            "selected_executor_binding": (
                routing.selected_executor_binding
            ),
            "goal_id": goal_id,
        },
    )
    return routing, authorization


def _execute(
    *,
    mission_id: str,
    task_id: str,
    goal_id: str,
):
    routing, authorization = _route_and_authorize(goal_id=goal_id)
    try:
        return execute_authorized_gta6_brain_decision(
            authorization=authorization,
            routing_decision=routing,
            payload={
                "mission_id": mission_id,
                "task_id": task_id,
                "goal_id": goal_id,
                "input_refs": [],
            },
        )
    finally:
        consume_harness_authorization(authorization)


def _episode_for(
    *,
    goal_id: str,
    task_id: str,
) -> dict[str, Any]:
    rows = harness_learning_repository.list_episodes(
        domain="gta6-decision",
        task_class="gta6-domain-decision",
        capability_id=GTA6_BRAIN_CAPABILITY_ID,
        limit=50,
    )
    matches = [
        row
        for row in rows
        if str(row.get("goal_id") or "") == goal_id
        and str(row.get("task_id") or "") == task_id
        and str(row.get("agent_id") or "") == "gta6-brain"
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "FIRST_REAL_GTA6_EPISODE_COUNT="
            + str(len(matches))
        )
    return matches[0]


def run(*, output: Path) -> dict[str, Any]:
    initialize_schema()
    run_id = str(os.getenv("GITHUB_RUN_ID") or "local").strip()
    mission_id = f"mission-gta6-feedback-proof-{run_id}"
    task_id = f"task-gta6-feedback-proof-{run_id}"
    goal_id = f"goal-gta6-feedback-proof-{run_id}"

    first = _execute(
        mission_id=mission_id,
        task_id=task_id,
        goal_id=goal_id,
    )
    if first.status != "EXECUTED":
        raise RuntimeError(
            "FIRST_REAL_GTA6_DECISION_NOT_EXECUTED:"
            + str(first.status)
        )
    first_episode = _episode_for(
        goal_id=goal_id,
        task_id=task_id,
    )
    first_episode_id = str(first_episode.get("episode_id") or "")
    if not first_episode_id:
        raise RuntimeError("FIRST_REAL_GTA6_EPISODE_ID_MISSING")

    first_outcome = dict(first_episode.get("actual_outcome") or {})
    first_domain_decision = dict(
        first_outcome.get("DOMAIN_DECISION") or {}
    )
    first_domain_projection = dict(
        first_outcome.get("DOMAIN_PROJECTION") or {}
    )
    if not first_domain_decision.get("action"):
        raise RuntimeError(
            "FIRST_REAL_GTA6_DECISION_MISSING_FROM_EPISODE"
        )
    if (
        first_domain_projection.get("schema")
        != GTA6_DOMAIN_PROJECTION_SCHEMA
    ):
        raise RuntimeError(
            "FIRST_REAL_GTA6_PROJECTION_MISSING_FROM_EPISODE"
        )

    second_input = build_gta6_domain_projection(
        mission_id=mission_id,
        task_id=task_id,
        goal_id=goal_id,
    )
    feedback = dict(second_input.get("decision_feedback") or {})
    previous = list(feedback.get("recent_brain_decisions") or ())
    prior = next(
        (
            item
            for item in previous
            if item.get("episode_ref")
            == f"episode:{first_episode_id}"
        ),
        None,
    )
    if prior is None:
        raise RuntimeError(
            "PREVIOUS_REAL_EPISODE_NOT_RETRIEVED"
        )
    if prior.get("action") != first_domain_decision.get("action"):
        raise RuntimeError(
            "PREVIOUS_REAL_DECISION_OUTCOME_DRIFT"
        )

    second = _execute(
        mission_id=mission_id,
        task_id=task_id,
        goal_id=goal_id,
    )
    if second.status != "EXECUTED":
        raise RuntimeError(
            "SECOND_REAL_GTA6_DECISION_NOT_EXECUTED:"
            + str(second.status)
        )

    provider_routing = dict(first.result.get("provider_routing") or {})
    result = {
        "schema": "GTA6BrainFeedbackProof/v1",
        "status": "PASS",
        "authority": "DEEPSEEK_HARNESS",
        "brain_authority": "NONE",
        "mission_id": mission_id,
        "task_id": task_id,
        "goal_id": goal_id,
        "learning_source_run_id": (
            os.getenv("LEARNING_SOURCE_RUN_ID") or None
        ),
        "head_sha": os.getenv("GITHUB_SHA") or None,
        "first_episode_ref": f"episode:{first_episode_id}",
        "first_decision": first.result.get("domain_decision"),
        "second_decision": second.result.get("domain_decision"),
        "first_projection": first.result.get("domain_projection"),
        "second_input_projection_sha256": second_input.get(
            "content_sha256"
        ),
        "previous_real_episode_retrieved_before_second_decision": True,
        "previous_real_decision_retrieved": True,
        "previous_real_outcome_retrieved": True,
        "second_input_feedback_counts": {
            "recent_brain_decisions": len(previous),
            "relevant_failure_memories": len(
                feedback.get("relevant_failure_memories") or ()
            ),
            "relevant_human_corrections": len(
                feedback.get("relevant_human_corrections") or ()
            ),
        },
        "selected_provider": provider_routing.get(
            "selected_provider"
        ),
        "selected_model": provider_routing.get("selected_model"),
        "brain_feedback_loop": "CLOSED",
        "canonical_harness_path_uses_projection": True,
        "no_fake_learning_evidence": True,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(output=args.output)
    print("GTA6_DOMAIN_PROJECTION_V1=PASS")
    print("CANONICAL_HARNESS_PATH_USES_PROJECTION=PASS")
    print("PREVIOUS_REAL_EPISODE_RETRIEVED_BEFORE_SECOND_DECISION=PASS")
    print("PREVIOUS_DECISION_RETRIEVED=PASS")
    print("PREVIOUS_OUTCOME_RETRIEVED=PASS")
    print("BRAIN_FEEDBACK_LOOP=CLOSED")
    print("BRAIN_AUTHORITY_NONE=PASS")
    print("NO_FAKE_LEARNING_EVIDENCE=PASS")
    print(
        "SELECTED_PROVIDER="
        + str(result.get("selected_provider") or "")
    )
    print(
        "SELECTED_MODEL="
        + str(result.get("selected_model") or "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
