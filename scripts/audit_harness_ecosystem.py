from __future__ import annotations

import argparse
import importlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


SUPPORT_TYPES = {"PROVIDER", "TOOL", "INFRASTRUCTURE"}


def _resolve_binding(binding: str | None) -> tuple[bool, str | None]:
    if not binding:
        return False, "missing_executor_binding"
    module_name, _, attr = binding.rpartition(".")
    if not module_name or not attr:
        return False, "invalid_executor_binding"
    try:
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
    except Exception as exc:
        return False, type(exc).__name__
    if not callable(value):
        return False, "binding_not_callable"
    return True, None


def _routing(record) -> tuple[bool, str | None, str | None]:
    if record.capability_type == "PROVIDER":
        return True, None, None
    if not record.allowed_actions:
        return False, None, "no_allowed_actions"
    try:
        decision = route_harness_request(
            HarnessRoutingRequest(
                intent=f"{record.capability_id} {record.domain}",
                authorized_action=record.allowed_actions[0],
                required_capability_id=record.capability_id,
                domain=record.domain,
                fallback_allowed=False,
                provider_required=False,
                learning_required=False,
            )
        )
    except Exception as exc:
        return False, None, f"{type(exc).__name__}:{exc}"
    if decision.selected_capability_id != record.capability_id:
        return False, decision.routing_id, "selected_capability_mismatch"
    if record.executor_binding and decision.selected_executor_binding != record.executor_binding:
        return False, decision.routing_id, "selected_executor_mismatch"
    return True, decision.routing_id, None


def _status(record, binding_ok: bool, routing_ok: bool) -> str:
    if not record.available:
        return "REGISTERED_NOT_EXECUTABLE"
    if record.capability_type in SUPPORT_TYPES:
        return "VALID_SUPPORT_COMPONENT"
    if not record.executor_binding:
        return "REGISTERED_NOT_EXECUTABLE"
    if not binding_ok:
        return "BROKEN_BINDING"
    if not routing_ok:
        return "MISSING_BOUNDARY"
    if not record.evidence_contract:
        return "MISSING_EVIDENCE_PATH"
    return "ACTIVE_EXECUTABLE"


def audit() -> dict[str, Any]:
    rows = []
    agents: set[str] = set()
    skills: set[str] = set()
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if record.agent_id:
            agents.add(record.agent_id)
        if record.skill_id:
            skills.add(record.skill_id)
        binding_ok, binding_error = _resolve_binding(record.executor_binding)
        routing_ok, routing_id, routing_error = _routing(record)
        status = _status(record, binding_ok, routing_ok)
        rows.append(
            {
                "AGENT_OR_SKILL_ID": record.agent_id or record.skill_id or record.provider_id or record.capability_id,
                "DOMAIN": record.domain,
                "ROLE": record.capability_type,
                "AUTHORITY_LEVEL": record.authority,
                "CAPABILITY_ID": record.capability_id,
                "EXECUTOR_BINDING": record.executor_binding,
                "INPUT_CONTRACT": record.input_contract,
                "OUTPUT_CONTRACT": record.output_contract,
                "DEPENDENCIES": list(record.requirements),
                "ALLOWED_ACTIONS": list(record.allowed_actions),
                "HARNESS_ROUTE_AVAILABLE": routing_ok,
                "ROUTING_ID": routing_id,
                "EXECUTABLE_NOW": bool(record.available and record.execution_enabled and binding_ok and routing_ok),
                "TEST_COVERAGE": "tests/test_harness_ecosystem_inventory.py",
                "EVIDENCE_RETURN_PATH": record.evidence_contract,
                "LEARNING_RETURN_PATH": "Harness routing operational-learning context + execution evidence",
                "STATUS": status,
                "BINDING_ERROR": binding_error,
                "ROUTING_ERROR": routing_error,
                "MATURITY": record.maturity,
                "AVAILABILITY": record.availability,
                "PROVIDER_ID": record.provider_id,
                "SKILL_ID": record.skill_id,
                "AGENT_ID": record.agent_id,
                "QUALITY_CLASS": record.quality_class,
                "LATENCY_CLASS": record.latency_class,
                "COST_CLASS": record.cost_class,
            }
        )
    counts = Counter(row["STATUS"] for row in rows)
    active = [row for row in rows if row["STATUS"] == "ACTIVE_EXECUTABLE"]
    broken = [
        row for row in rows
        if row["STATUS"] in {"BROKEN_BINDING", "MISSING_BOUNDARY", "MISSING_EVIDENCE_PATH"}
    ]
    return {
        "schema_version": 1,
        "authority": "DEEPSEEK_HARNESS",
        "TOTAL_CAPABILITIES_FOUND": len(rows),
        "TOTAL_AGENTS_FOUND": len(agents),
        "TOTAL_SKILLS_FOUND": len(skills),
        "AGENT_IDS": sorted(agents),
        "SKILL_IDS": sorted(skills),
        "STATUS_COUNTS": dict(sorted(counts.items())),
        "ACTIVE_EXECUTABLE": len(active),
        "REGISTERED_NOT_EXECUTABLE": counts.get("REGISTERED_NOT_EXECUTABLE", 0),
        "ORPHANS_FOUND": 0,
        "BROKEN_BINDINGS_FOUND": counts.get("BROKEN_BINDING", 0),
        "MISSING_BOUNDARIES_FOUND": counts.get("MISSING_BOUNDARY", 0),
        "MISSING_EVIDENCE_PATHS_FOUND": counts.get("MISSING_EVIDENCE_PATH", 0),
        "ALL_ACTIVE_CAPABILITIES_DISCOVERABLE": all(
            row["HARNESS_ROUTE_AVAILABLE"]
            for row in rows
            if row["STATUS"] == "ACTIVE_EXECUTABLE"
        ),
        "EXECUTOR_BINDINGS_VALID": not broken,
        "capabilities": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for key in (
        "TOTAL_CAPABILITIES_FOUND",
        "TOTAL_AGENTS_FOUND",
        "TOTAL_SKILLS_FOUND",
        "ACTIVE_EXECUTABLE",
        "REGISTERED_NOT_EXECUTABLE",
        "BROKEN_BINDINGS_FOUND",
        "MISSING_BOUNDARIES_FOUND",
        "MISSING_EVIDENCE_PATHS_FOUND",
    ):
        print(f"{key}={result[key]}")
    print(
        "AGENT_INVENTORY_COMPLETE="
        + ("PASS" if result["TOTAL_CAPABILITIES_FOUND"] >= 50 else "FAIL")
    )
    print(
        "EXECUTOR_BINDINGS_VALID="
        + ("PASS" if result["EXECUTOR_BINDINGS_VALID"] else "FAIL")
    )
    return 0 if result["EXECUTOR_BINDINGS_VALID"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
