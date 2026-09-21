from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.database import harness_learning_repository as learning_repository
from app.database.harness_authorization_repository import list_recent_harness_authorizations
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY


def build_capability_usage_audit(*, authorization_limit: int = 1000, episode_limit: int = 5000) -> dict[str, Any]:
    episodes = learning_repository.list_episodes(limit=episode_limit)
    auths = list_recent_harness_authorizations(limit=authorization_limit)
    competence = learning_repository.list_competence(limit=5000)

    by_cap_eps: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in episodes:
        cap = str(row.get("capability_id") or "")
        if cap:
            by_cap_eps[cap].append(row)

    selected: dict[str, int] = defaultdict(int)
    for row in auths:
        lineage = dict(row.get("lineage") or {})
        cap = str(lineage.get("capability_id") or "")
        if cap:
            selected[cap] += 1

    by_comp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in competence:
        cap = str(row.get("capability_id") or "")
        if cap:
            by_comp[cap].append(row)

    rows = []
    unreachable = []
    never_selected = []
    blocked = []
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        eps = by_cap_eps.get(record.capability_id, [])
        successes = sum(1 for e in eps if e.get("status") == "COMPLETED")
        failures = sum(1 for e in eps if e.get("status") in {"FAILED", "BLOCKED", "CANCELLED"})
        reviews = sum(1 for e in eps if bool(e.get("human_intervention")))
        reachable = bool(record.execution_enabled and record.executor_binding)
        reason = None
        if not reachable:
            reason = "missing executable Registry binding or capability unavailable"
            unreachable.append(record.capability_id)
        elif selected.get(record.capability_id, 0) == 0 and not eps:
            never_selected.append(record.capability_id)
        if not record.available:
            blocked.append(record.capability_id)
        rows.append({
            "capability_id": record.capability_id,
            "domain": record.domain,
            "capability_type": record.capability_type,
            "available": record.available,
            "routable": reachable,
            "execution_count": len(eps),
            "selected_count": selected.get(record.capability_id, 0),
            "successful_count": successes,
            "failure_count": failures,
            "review_count": reviews,
            "last_execution": max((str(e.get("finished_at") or "") for e in eps), default=None),
            "competence_records": len(by_comp.get(record.capability_id, [])),
            "blocked_reason": reason,
            "classification": (
                "REGISTERED_BUT_UNREACHABLE" if not reachable
                else "REGISTERED_BUT_NEVER_SELECTED" if selected.get(record.capability_id, 0) == 0 and not eps
                else "ACTIVE_USAGE"
            ),
        })

    return {
        "status": "PASS",
        "registered": len(rows),
        "available": sum(1 for row in rows if row["available"]),
        "routable": sum(1 for row in rows if row["routable"]),
        "actually_executed": sum(1 for row in rows if row["execution_count"] > 0),
        "orphaned": unreachable,
        "never_selected": never_selected,
        "blocked": blocked,
        "records": rows,
        "CAPABILITY_USAGE_AUDIT": "PASS",
        "NO_ORPHAN_EXECUTION_PATHS": "PASS" if not unreachable else "FAIL",
        "authority": "DEEPSEEK_HARNESS",
    }
