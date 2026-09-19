from __future__ import annotations

import argparse
import ast
import importlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.services.agent_office.munder_adapter import registered_worker_runners
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.global_capability_registry_base import ADDY_SKILLS
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


ROOT = Path(__file__).resolve().parents[1]
STATUS_ORDER = (
    "ACTIVE_EXECUTABLE",
    "REGISTERED_NOT_EXECUTABLE",
    "DUPLICATE",
    "ORPHAN",
    "BROKEN_BINDING",
    "MISSING_BOUNDARY",
    "MISSING_TEST",
    "MISSING_EVIDENCE_PATH",
    "DEPRECATED",
    "VALID_SUPPORT_COMPONENT",
)
KNOWN_AGENT_CLASS_POLICY = {
    "GTA6MasterAgent": {
        "identity": "gta6-master-agent",
        "status": "VALID_SUPPORT_COMPONENT",
        "role": "SUBORDINATE_DECISION_EXECUTION_AGENT",
        "authority": "HARNESS_AUTHORIZATION_REQUIRED",
        "evidence": "app.database.gta6_master_agent_repository.create_gta6_master_agent_run",
        "learning": "master-agent run persistence; no standalone capability episode boundary",
        "note": (
            "Concrete executable class consumed under Harness-routed AI provider and "
            "HarnessAuthorization. It is intentionally not a second control plane."
        ),
    },
    "GTA6Brain": {
        "identity": "gta6-brain",
        "status": "ACTIVE_EXECUTABLE",
        "role": "GTA6_DOMAIN_DECISION_SPECIALIST",
        "authority": "SUBORDINATE_ONLY",
        "evidence": "gta6.brain.decide BrainDecision + AgentInvocationReceipt",
        "learning": "observed Harness episode via gta6.brain.decide",
        "note": (
            "Concrete domain specialist is independently discoverable/routable through "
            "gta6.brain.decide and cannot authorize or execute its recommended action."
        ),
    },
}


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


def _capability_status(record, binding_ok: bool, routing_ok: bool) -> str:
    if str(record.implementation or "").startswith("DEPRECATED SUPPORT PATH:"):
        return "DEPRECATED"
    if not record.available or not record.execution_enabled:
        return "REGISTERED_NOT_EXECUTABLE"
    if record.capability_type == "PROVIDER":
        return "VALID_SUPPORT_COMPONENT"
    if not record.executor_binding:
        return "BROKEN_BINDING"
    if not binding_ok:
        return "BROKEN_BINDING"
    if not routing_ok:
        return "MISSING_BOUNDARY"
    if not record.evidence_contract:
        return "MISSING_EVIDENCE_PATH"
    return "ACTIVE_EXECUTABLE"


def _instruction_test_path(record) -> str:
    if record.capability_id.startswith("addy:"):
        return "tests/test_addy_24_certification.py + Addy 24 Live Semantic Smoke + legacy Codex adapter tests"
    if record.capability_id.startswith("youtube.department."):
        return "tests/test_system_synergy_service.py + tests/test_youtube_department_learning_boundary.py"
    if record.capability_id == "gta6.fact-check":
        return "tests/test_gta6_fact_check_service.py + tests/test_gta6_fact_check_swarm_proof_unit.py"
    if record.capability_id == "agent-office.execute":
        return "tests/test_agent_office_service.py + Agent Office GitHub Actions proof"
    return "tests/test_harness_ecosystem_inventory.py"


def _capability_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        binding_ok, binding_error = _resolve_binding(record.executor_binding)
        routing_ok, routing_id, routing_error = _routing(record)
        status = _capability_status(record, binding_ok, routing_ok)
        rows.append(
            {
                "AGENT_OR_SKILL_ID": (
                    record.agent_id or record.skill_id or record.provider_id or record.capability_id
                ),
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
                "EXECUTABLE_NOW": bool(
                    record.available
                    and record.execution_enabled
                    and binding_ok
                    and routing_ok
                ),
                "TEST_COVERAGE": _instruction_test_path(record),
                "EVIDENCE_RETURN_PATH": record.evidence_contract,
                "LEARNING_RETURN_PATH": (
                    "Harness execution evidence / observed episode when capability wrapper captures receipts"
                ),
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
                "INSTRUCTION_PATH": record.instruction_path,
            }
        )
    return rows


def _python_agent_classes() -> list[dict[str, str]]:
    discovered: list[dict[str, str]] = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not (node.name.endswith("Agent") or node.name.endswith("Brain")):
                continue
            discovered.append(
                {
                    "class_name": node.name,
                    "path": path.relative_to(ROOT).as_posix(),
                    "line": str(node.lineno),
                }
            )
    return discovered


def _dsh_declared_agents() -> list[dict[str, Any]]:
    """Inventory declarative DeepSeek Harness agent-loop entries from canonical config."""
    path = ROOT / ".dsh" / "cordis.patch.yml"
    if not path.is_file():
        return []

    lines = path.read_text(encoding="utf-8").splitlines()
    rows: list[dict[str, Any]] = []
    in_agent_loop = False
    in_agents = False
    current: dict[str, Any] | None = None

    for raw in lines:
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip(" "))

        if stripped == "- id: agent-loop":
            in_agent_loop = True
            in_agents = False
            current = None
            continue

        if in_agent_loop and indent == 4 and stripped == "agents:":
            in_agents = True
            continue

        if not in_agents:
            continue

        if indent <= 2 and stripped.startswith("- "):
            break

        if indent == 6 and stripped.startswith("- id: "):
            if current is not None:
                rows.append(current)
            current = {
                "agent_id": stripped.split(":", 1)[1].strip(),
                "session_id": None,
                "provider": None,
                "model": None,
                "source": ".dsh/cordis.patch.yml",
                "driver": "@deepseek-ai/dsh-agent-loop",
                "boot_declared": True,
                "semantic_turn_proven": False,
            }
            continue

        if current is None or indent != 8 or ":" not in stripped:
            continue

        key, value = stripped.split(":", 1)
        value = value.strip()
        if key == "sessionId":
            current["session_id"] = value
        elif key == "provider":
            current["provider"] = value
        elif key == "model":
            current["model"] = value

    if current is not None:
        rows.append(current)

    return rows


def _dsh_skills() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    root = ROOT / ".dsh" / "skills"
    if not root.is_dir():
        return rows
    records = GLOBAL_CAPABILITY_REGISTRY.all()
    for skill_file in sorted(root.glob("*/SKILL.md")):
        relative = skill_file.relative_to(ROOT).as_posix()
        folder_id = skill_file.parent.name
        matches = [
            record
            for record in records
            if record.instruction_path == relative
            or record.skill_id == folder_id
            or str(record.skill_id or "").replace(".", "-") == folder_id
        ]
        rows.append(
            {
                "skill_id": (
                    matches[0].skill_id if len(matches) == 1 and matches[0].skill_id else folder_id
                ),
                "folder_id": folder_id,
                "path": relative,
                "non_empty": bool(skill_file.read_text(encoding="utf-8").strip()),
                "registry_capabilities": [record.capability_id for record in matches],
                "status": (
                    "ACTIVE_EXECUTABLE"
                    if any(
                        record.available
                        and record.execution_enabled
                        and record.executor_binding
                        for record in matches
                    )
                    else "ORPHAN" if not matches else "REGISTERED_NOT_EXECUTABLE"
                ),
            }
        )
    return rows


def _identity_inventory(capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    identities: dict[tuple[str, str], dict[str, Any]] = {}

    def ensure(kind: str, identity: str) -> dict[str, Any]:
        key = (kind, identity)
        if key not in identities:
            identities[key] = {
                "IDENTITY_KIND": kind,
                "AGENT_OR_SKILL_ID": identity,
                "SOURCES": [],
                "CAPABILITY_IDS": [],
                "EXECUTOR_BINDINGS": [],
                "DOMAINS": [],
                "ALLOWED_ACTIONS": [],
                "HARNESS_ROUTE_AVAILABLE": False,
                "EXECUTABLE_NOW": False,
                "TEST_COVERAGE": [],
                "EVIDENCE_RETURN_PATHS": [],
                "LEARNING_RETURN_PATHS": [],
                "STATUS": "REGISTERED_NOT_EXECUTABLE",
                "NOTES": [],
            }
        return identities[key]

    def merge_status(current: str, candidate: str) -> str:
        if current == "ACTIVE_EXECUTABLE" or candidate == "ACTIVE_EXECUTABLE":
            return "ACTIVE_EXECUTABLE"
        priority = {
            "BROKEN_BINDING": 10,
            "MISSING_BOUNDARY": 9,
            "MISSING_EVIDENCE_PATH": 8,
            "ORPHAN": 7,
            "MISSING_TEST": 6,
            "REGISTERED_NOT_EXECUTABLE": 5,
            "VALID_SUPPORT_COMPONENT": 4,
            "DEPRECATED": 3,
            "DUPLICATE": 2,
        }
        return candidate if priority.get(candidate, 0) > priority.get(current, 0) else current

    for row in capabilities:
        identities_for_record: list[tuple[str, str]] = []
        if row.get("AGENT_ID"):
            identities_for_record.append(("AGENT", str(row["AGENT_ID"])))
        if row.get("SKILL_ID"):
            identities_for_record.append(("SKILL", str(row["SKILL_ID"])))
        for kind, identity in identities_for_record:
            item = ensure(kind, identity)
            item["SOURCES"].append("GLOBAL_CAPABILITY_REGISTRY")
            item["CAPABILITY_IDS"].append(row["CAPABILITY_ID"])
            if row.get("EXECUTOR_BINDING"):
                item["EXECUTOR_BINDINGS"].append(row["EXECUTOR_BINDING"])
            item["DOMAINS"].append(row["DOMAIN"])
            item["ALLOWED_ACTIONS"].extend(row["ALLOWED_ACTIONS"])
            item["HARNESS_ROUTE_AVAILABLE"] = (
                item["HARNESS_ROUTE_AVAILABLE"] or row["HARNESS_ROUTE_AVAILABLE"]
            )
            item["EXECUTABLE_NOW"] = item["EXECUTABLE_NOW"] or row["EXECUTABLE_NOW"]
            item["TEST_COVERAGE"].append(row["TEST_COVERAGE"])
            if row.get("EVIDENCE_RETURN_PATH"):
                item["EVIDENCE_RETURN_PATHS"].append(row["EVIDENCE_RETURN_PATH"])
            item["LEARNING_RETURN_PATHS"].append(row["LEARNING_RETURN_PATH"])
            item["STATUS"] = merge_status(item["STATUS"], row["STATUS"])

    # Selected Higgsfield skills are real Codex-discoverable skills, while
    # generation capabilities remain blocked until unattended authentication is proven.
    higgsfield_skills = sorted(
        record.capability_id
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
        if record.provider_id == "higgsfield"
    )
    for skill in higgsfield_skills:
        item = ensure("SKILL", skill)
        item["SOURCES"].extend(
            [
                "higgsfield-ai/skills pinned runtime pack",
                "scripts/agent-tooling/bootstrap.sh",
                "scripts/agent-tooling/check_discovery.py",
            ]
        )
        record = GLOBAL_CAPABILITY_REGISTRY.get(skill)
        if record is not None:
            item["CAPABILITY_IDS"].append(record.capability_id)
            item["DOMAINS"].append(record.domain)
            item["ALLOWED_ACTIONS"].extend(record.allowed_actions)
            item["TEST_COVERAGE"].append("GitHub Actions native Codex skills/list discovery")
            item["EVIDENCE_RETURN_PATHS"].append(record.evidence_contract or "CapabilityEvidence")
            item["LEARNING_RETURN_PATHS"].append("not applicable while generation is BLOCKED")
            item["STATUS"] = merge_status(item["STATUS"], "REGISTERED_NOT_EXECUTABLE")
            item["NOTES"].append(
                "Skill is installed/discoverable in Codex tooling; external generation remains BLOCKED until unattended auth is proven."
            )

    # The pinned Addy pack is an external runtime source, not 24 checked-in folders.
    for skill in ADDY_SKILLS:
        capability_id = f"addy:{skill}"
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        item = ensure("SKILL", skill)
        item["SOURCES"].extend(
            [
                "addyosmani/agent-skills pinned runtime pack",
                "scripts/agent-tooling/bootstrap.sh",
                "scripts/agent-tooling/certify_addy_24.py",
            ]
        )
        if record is None:
            item["STATUS"] = merge_status(item["STATUS"], "ORPHAN")
            item["NOTES"].append("Pinned Addy skill missing from global Registry")
        else:
            item["NOTES"].append(
                "Materialized from pinned source on cloud runner; one selected skill per Harness-governed semantic execution"
            )

    for row in _dsh_skills():
        item = ensure("SKILL", str(row["skill_id"]))
        item["SOURCES"].append(str(row["path"]))
        item["STATUS"] = merge_status(item["STATUS"], str(row["status"]))
        if not row["non_empty"]:
            item["STATUS"] = merge_status(item["STATUS"], "BROKEN_BINDING")
            item["NOTES"].append("SKILL.md is empty")
        if not row["registry_capabilities"]:
            item["NOTES"].append("Local DSH skill has no Registry mapping")

    # Native DeepSeek Harness agents declared in agent-loop config.
    for native in _dsh_declared_agents():
        item = ensure("HARNESS_NATIVE_AGENT", str(native["agent_id"]))
        item["SOURCES"].append(str(native["source"]))
        if str(native["agent_id"]) == "gta6-master":
            item["SOURCES"].append(".dsh/plugins/gta6-master-activation.mjs")
        item["DOMAINS"].append("harness-native")
        item["EXECUTOR_BINDINGS"].append(str(native["driver"]))
        item["STATUS"] = merge_status(item["STATUS"], "VALID_SUPPORT_COMPONENT")
        item["EXECUTABLE_NOW"] = False
        item["NOTES"].append(
            "Declaratively booted by dsh-agent-loop when the configured model provider is reachable; "
            "inventory does not claim a semantic model turn."
        )
        item["EVIDENCE_RETURN_PATHS"].append("DeepSeek Harness session/event log")
        item["LEARNING_RETURN_PATHS"].append("DeepSeek Harness durable session + BR Harness evidence")
        item["TEST_COVERAGE"].append(".github/workflows/deepseek-harness.yml")

    # Worker engines are concrete execution identities inside Agent Office.
    workers = registered_worker_runners()
    for worker_id, runner in sorted(workers.items()):
        item = ensure("WORKER_ENGINE", worker_id)
        item["SOURCES"].append("app.services.agent_office.munder_adapter.registered_worker_runners")
        item["EXECUTOR_BINDINGS"].append(f"{runner.__module__}.{runner.__name__}")
        item["DOMAINS"].append("development")
        item["ALLOWED_ACTIONS"].append("DEVELOPMENT")
        item["HARNESS_ROUTE_AVAILABLE"] = True
        item["EXECUTABLE_NOW"] = True
        if worker_id == "codex":
            item["STATUS"] = "ACTIVE_EXECUTABLE"
            item["NOTES"].append(
                "Agent Office Codex worker engine remains a support executor; "
                "the canonical 24 Addy semantic capabilities route through addy-agent-skills"
            )
        else:
            item["STATUS"] = "ACTIVE_EXECUTABLE"
            item["NOTES"].append(
                "Internal deterministic Agent Office worker engine selected only through agent-office.execute"
            )
        item["TEST_COVERAGE"].append("tests/test_agent_office_service.py")
        item["EVIDENCE_RETURN_PATHS"].append(
            "AgentOfficeExecutionResult.per_agent_results + sanitized evidence"
        )
        item["LEARNING_RETURN_PATHS"].append("Agent Office result -> DeepSeek Harness")

    # Munder's upstream GOD/Michael role is deliberately reduced to a delegated coordinator.
    coordinator = ensure("AGENT", "agent-office-coordinator")
    coordinator["SOURCES"].extend(
        [
            "integrations/munder_difflin/UPSTREAM.lock",
            "integrations/munder_difflin/config/policy.json",
        ]
    )
    coordinator["NOTES"].append(
        "Upstream GOD/Michael authority is not imported; BR boundary is DELEGATED_ONLY"
    )

    # Concrete Python agent/brain classes are included even when not Registry identities.
    for discovered in _python_agent_classes():
        policy = KNOWN_AGENT_CLASS_POLICY.get(discovered["class_name"])
        if policy is None:
            item = ensure("CODE_AGENT_CLASS", discovered["class_name"])
            item["SOURCES"].append(
                f"{discovered['path']}:{discovered['line']}"
            )
            item["STATUS"] = merge_status(item["STATUS"], "ORPHAN")
            item["NOTES"].append("Agent/Brain class discovered by AST without explicit audit policy")
            continue
        item = ensure("AGENT", policy["identity"])
        item["SOURCES"].append(f"{discovered['path']}:{discovered['line']}")
        item["DOMAINS"].append("gta6")
        item["STATUS"] = merge_status(item["STATUS"], policy["status"])
        item["EVIDENCE_RETURN_PATHS"].append(policy["evidence"])
        item["LEARNING_RETURN_PATHS"].append(policy["learning"])
        item["NOTES"].append(policy["note"])
        item["TEST_COVERAGE"].append(
            "tests/test_gta6_master_agent.py"
            if discovered["class_name"] == "GTA6MasterAgent"
            else "tests/test_gta6_brain.py"
        )

    for item in identities.values():
        for field in (
            "SOURCES",
            "CAPABILITY_IDS",
            "EXECUTOR_BINDINGS",
            "DOMAINS",
            "ALLOWED_ACTIONS",
            "TEST_COVERAGE",
            "EVIDENCE_RETURN_PATHS",
            "LEARNING_RETURN_PATHS",
            "NOTES",
        ):
            item[field] = sorted(set(item[field]))
    return sorted(
        identities.values(),
        key=lambda item: (item["IDENTITY_KIND"], item["AGENT_OR_SKILL_ID"]),
    )


def audit() -> dict[str, Any]:
    capabilities = _capability_rows()
    identities = _identity_inventory(capabilities)
    capability_counts = Counter(row["STATUS"] for row in capabilities)
    identity_counts = Counter(row["STATUS"] for row in identities)

    agent_ids = {
        row["AGENT_OR_SKILL_ID"]
        for row in identities
        if row["IDENTITY_KIND"] in {"AGENT", "HARNESS_NATIVE_AGENT"}
    }
    skill_ids = {
        row["AGENT_OR_SKILL_ID"]
        for row in identities
        if row["IDENTITY_KIND"] == "SKILL"
    }
    worker_ids = {
        row["AGENT_OR_SKILL_ID"]
        for row in identities
        if row["IDENTITY_KIND"] == "WORKER_ENGINE"
    }
    addy_ids = set(ADDY_SKILLS)
    higgsfield_ids = {
        record.capability_id
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
        if record.provider_id == "higgsfield"
    }
    observed_addy = {
        row["AGENT_OR_SKILL_ID"]
        for row in identities
        if row["IDENTITY_KIND"] == "SKILL"
        and row["AGENT_OR_SKILL_ID"] in addy_ids
    }
    observed_higgsfield = {
        row["AGENT_OR_SKILL_ID"]
        for row in identities
        if row["IDENTITY_KIND"] == "SKILL"
        and row["AGENT_OR_SKILL_ID"] in higgsfield_ids
    }

    capability_blockers = [
        row
        for row in capabilities
        if row["STATUS"] in {
            "BROKEN_BINDING",
            "MISSING_BOUNDARY",
            "MISSING_EVIDENCE_PATH",
        }
        and row["AVAILABILITY"] == "AVAILABLE"
    ]
    identity_blockers = [
        row
        for row in identities
        if row["STATUS"] in {
            "BROKEN_BINDING",
            "MISSING_BOUNDARY",
            "MISSING_EVIDENCE_PATH",
            "ORPHAN",
        }
    ]

    return {
        "schema_version": 2,
        "authority": "DEEPSEEK_HARNESS",
        "inventory_scope": {
            "global_registry": True,
            "local_dsh_skills": True,
            "pinned_addy_agent_skills": True,
            "agent_office_worker_engines": True,
            "python_agent_brain_classes": True,
            "deepseek_harness_agent_loop_config": True,
            "munder_dynamic_upstream_agents_counted_as_active": False,
        },
        "TOTAL_CAPABILITIES_FOUND": len(capabilities),
        "TOTAL_AGENTS_FOUND": len(agent_ids),
        "TOTAL_SKILLS_FOUND": len(skill_ids),
        "TOTAL_WORKER_ENGINES_FOUND": len(worker_ids),
        "NATIVE_HARNESS_DECLARED_AGENT_COUNT": len(_dsh_declared_agents()),
        "NATIVE_HARNESS_DECLARED_AGENT_IDS": sorted(item["agent_id"] for item in _dsh_declared_agents()),
        "NATIVE_HARNESS_AGENT_RUNTIME": "DSH_AGENT_LOOP_DECLARATIVE",
        "NATIVE_HARNESS_SEMANTIC_EXECUTION_PROVEN": False,
        "ADDY_SKILLS_EXPECTED": 24,
        "ADDY_SKILLS_FOUND": len(observed_addy),
        "ADDY_SKILL_IDS": sorted(observed_addy),
        "HIGGSFIELD_SKILLS_EXPECTED": 4,
        "HIGGSFIELD_SKILLS_FOUND": len(observed_higgsfield),
        "HIGGSFIELD_SKILL_IDS": sorted(observed_higgsfield),
        "AGENT_IDS": sorted(agent_ids),
        "SKILL_IDS": sorted(skill_ids),
        "WORKER_ENGINE_IDS": sorted(worker_ids),
        "CAPABILITY_STATUS_COUNTS": dict(sorted(capability_counts.items())),
        "IDENTITY_STATUS_COUNTS": dict(sorted(identity_counts.items())),
        "ACTIVE_EXECUTABLE": capability_counts.get("ACTIVE_EXECUTABLE", 0),
        "REGISTERED_NOT_EXECUTABLE": capability_counts.get("REGISTERED_NOT_EXECUTABLE", 0),
        "ORPHANS_FOUND": identity_counts.get("ORPHAN", 0),
        "BROKEN_BINDINGS_FOUND": capability_counts.get("BROKEN_BINDING", 0),
        "MISSING_BOUNDARIES_FOUND": (
            capability_counts.get("MISSING_BOUNDARY", 0)
            + identity_counts.get("MISSING_BOUNDARY", 0)
        ),
        "MISSING_EVIDENCE_PATHS_FOUND": capability_counts.get("MISSING_EVIDENCE_PATH", 0),
        "AGENT_INVENTORY_COMPLETE": (
            len(observed_addy) == 24
            and len(observed_higgsfield) == 4
            and len(_dsh_skills()) >= 6
            and "addy-agent-skills" in agent_ids
            and "codex" in worker_ids
            and "gta6-master-agent" in agent_ids
            and "gta6-brain" in agent_ids
            and "agent-office-coordinator" in agent_ids
        ),
        "ALL_ACTIVE_CAPABILITIES_DISCOVERABLE": all(
            row["HARNESS_ROUTE_AVAILABLE"]
            for row in capabilities
            if row["STATUS"] == "ACTIVE_EXECUTABLE"
        ),
        "EXECUTOR_BINDINGS_VALID": not capability_blockers,
        "IDENTITY_INTEGRATION_BLOCKERS": [
            {
                "id": row["AGENT_OR_SKILL_ID"],
                "kind": row["IDENTITY_KIND"],
                "status": row["STATUS"],
                "notes": row["NOTES"],
            }
            for row in identity_blockers
        ],
        "capabilities": capabilities,
        "identities": identities,
        "local_dsh_skills": _dsh_skills(),
        "python_agent_classes": _python_agent_classes(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for key in (
        "TOTAL_CAPABILITIES_FOUND",
        "TOTAL_AGENTS_FOUND",
        "TOTAL_SKILLS_FOUND",
        "TOTAL_WORKER_ENGINES_FOUND",
        "NATIVE_HARNESS_DECLARED_AGENT_COUNT",
        "ADDY_SKILLS_FOUND",
        "HIGGSFIELD_SKILLS_FOUND",
        "ACTIVE_EXECUTABLE",
        "REGISTERED_NOT_EXECUTABLE",
        "ORPHANS_FOUND",
        "BROKEN_BINDINGS_FOUND",
        "MISSING_BOUNDARIES_FOUND",
        "MISSING_EVIDENCE_PATHS_FOUND",
    ):
        print(f"{key}={result[key]}")
    print(
        "AGENT_INVENTORY_COMPLETE="
        + ("PASS" if result["AGENT_INVENTORY_COMPLETE"] else "FAIL")
    )
    print(
        "ADDY_24_INVENTORIED="
        + ("PASS" if result["ADDY_SKILLS_FOUND"] == 24 else "FAIL")
    )
    print(
        "HIGGSFIELD_4_INVENTORIED="
        + ("PASS" if result["HIGGSFIELD_SKILLS_FOUND"] == 4 else "FAIL")
    )
    print(
        "ALL_ACTIVE_CAPABILITIES_DISCOVERABLE="
        + ("PASS" if result["ALL_ACTIVE_CAPABILITIES_DISCOVERABLE"] else "FAIL")
    )
    print(
        "EXECUTOR_BINDINGS_VALID="
        + ("PASS" if result["EXECUTOR_BINDINGS_VALID"] else "FAIL")
    )
    return 0 if (
        result["AGENT_INVENTORY_COMPLETE"]
        and result["EXECUTOR_BINDINGS_VALID"]
        and result["HIGGSFIELD_SKILLS_FOUND"] == 4
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
