"""Harness capability utilization audit — catalog != availability != execution proof.

This auditor does not authorize, execute, reroute, install, spend, learn, or promote.
It safely probes local REA discovery commands and publishes sanitized evidence.
Do not use output to give an agent permissions it does not already possess.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "BRHarnessCapabilityUtilization/v1"
REA_VERSION = "6.0.0"
REA_DISCOVERY_COMMANDS = ("capabilities", "providers", "doctor")
_IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_./:-]{0,95}$")


def _hash(data: Any) -> str:
    return hashlib.sha256(json.dumps(
        data, sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(",", ":"),
    ).encode()).hexdigest()


def _collect_names(data: Any, *, max_depth: int = 6, limit: int = 240) -> list[str]:
    """Only catalog identifiers, no arbitrary values, source text or paths."""
    discovered: set[str] = set()
    def walk(node: Any, level: int = 0) -> None:
        if level > max_depth or len(discovered) >= limit:
            return
        if isinstance(node, dict):
            for key in ("id", "capability_id", "tool_id", "name"):
                candidate = node.get(key)
                if isinstance(candidate, str) and _IDENTIFIER.fullmatch(candidate):
                    discovered.add(candidate)
            for key, value in list(node.items())[:200]:
                if isinstance(value, (dict, list)):
                    walk(value, level + 1)
        elif isinstance(node, list):
            for child in node[:200]:
                walk(child, level + 1)
    walk(data)
    return sorted(discovered)[:limit]


def probe_rea_discovery(binary_path: str | Path, *, timeout_seconds: int = 20) -> dict[str, Any]:
    if type(timeout_seconds) is not int or not 3 <= timeout_seconds <= 60:
        raise ValueError("REA_DISCOVERY_TIMEOUT_INVALID")
    binary = Path(binary_path)
    if not binary.is_absolute() or not binary.is_file():
        raise ValueError("REA_DISCOVERY_ABSOLUTE_BINARY_REQUIRED")
    if not os.access(binary, os.X_OK):
        raise ValueError("REA_DISCOVERY_BINARY_NOT_EXECUTABLE")
    def run(args: list[str]) -> subprocess.CompletedProcess:
        try:
            return subprocess.run([str(binary), *args], text=True, capture_output=True,
                                  timeout=timeout_seconds, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("REA_DISCOVERY_PROBE_UNAVAILABLE") from exc
    version = run(["--version"])
    if version.returncode != 0 or version.stdout.strip() != REA_VERSION:
        raise ValueError("REA_DISCOVERY_VERSION_PIN_MISMATCH")
    checked = {}
    for name in REA_DISCOVERY_COMMANDS:
        result = run([name, "--json"])
        blob = result.stdout.encode("utf-8", "strict")
        if len(blob) > 2_000_000:
            raise ValueError("REA_DISCOVERY_JSON_TOO_LARGE")
        valid = False
        parsed: Any = None
        try:
            parsed = json.loads(result.stdout)
            valid = isinstance(parsed, (dict,list))
        except (ValueError, TypeError):
            pass
        checked[name] = {
            "command": name, "exit_code": result.returncode,
            "json_valid": valid,
            "output_sha256": hashlib.sha256(blob).hexdigest(),
            "catalog_identifiers": _collect_names(parsed) if valid else [],
            "readiness": (
                "DISCOVERY_SUCCEEDED" if result.returncode == 0 and valid
                else "DIAGNOSTIC_INCOMPLETE_OR_UNAVAILABLE"
            ),
        }
    return {
        "schema_version": "BRREAProviderDiscoveryEvidence/v1",
        "rea_version": REA_VERSION,
        "discovery_only": True,
        "native_provider_ready": False,  # A doctor JSON parser is not provider proof.
        "native_provider_status": "INDEPENDENT_PROVIDER_ATTESTATION_REQUIRED",
        "no_application_executed": True,
        "mcp_registration": "NOT_ATTEMPTED",
        "catalog": checked,
    }


# Enumerated operation surfaces; documentation claims are not proofs.
# Each entry corresponds to an individual measurable task, not a tool-count proxy.
IRIS_SURFACES = (
    ("viewport_capture", "LOCAL_MEASURED"),
    ("element_capture", "LOCAL_MEASURED"),
    ("full_page_capture", "E2E_REQUIRED"),
    ("dark_theme_capture", "E2E_REQUIRED"),
    ("selector_padding", "E2E_REQUIRED"),
    ("wait_for_selector", "E2E_REQUIRED"),
    ("custom_viewports", "POLICY_BOUNDED"),
    ("batch_concurrency", "NOT_ENABLED"),
    ("persistent_mcp_server", "NOT_ENABLED"),
    ("live_public_pages", "NETWORK_CONTAINMENT_REQUIRED"),
)
REA_SURFACES = (
    ("static_javascript", "LOCAL_MEASURED"),
    ("capability_inventory", "E2E_REQUIRED"),
    ("provider_doctor", "E2E_REQUIRED"),
    ("provider_inventory", "E2E_REQUIRED"),
    ("native_ghidra", "NATIVE_PROVIDER_REQUIRED"),
    ("native_hopper", "NATIVE_PROVIDER_REQUIRED"),
    ("native_call_graphs", "NATIVE_PROVIDER_REQUIRED"),
    ("native_pseudocode", "NATIVE_PROVIDER_REQUIRED"),
    ("managed_assembly_triage", "INTEGRATION_REQUIRED"),
    ("javascript_source_map", "INTEGRATION_REQUIRED"),
    ("electron_observation", "CONTAINED_RUNTIME_REQUIRED"),
    ("browser_network_observation", "NETWORK_CONTAINMENT_REQUIRED"),
    ("mcp_sessions", "CONTROLLED_MCP_GATE_REQUIRED"),
)


def capability_utilization_report(*, registry: Any, rea_probe: dict | None = None) -> dict:
    """Audit declared Harness registry and probe-linked tool surfaces, no fake pass."""
    if rea_probe is not None and rea_probe.get("schema_version") != "BRREAProviderDiscoveryEvidence/v1":
        raise ValueError("REA_DISCOVERY_RECEIPT_SCHEMA_INVALID")
    rows = []
    for record in registry.all():
        declared = bool(record.execution_enabled)
        rows.append({
            "capability_id": record.capability_id,
            "domain": record.domain,
            "registry_available": record.available,
            "executor_declared": declared,
            "runtime_execution_tested_here": False,
            "external_provider_ready_here": False,
            "authorized_actions": list(record.allowed_actions),
            "cost_class": record.cost_class,
            "requires_human_approval_to_promote": True,
        })
    if len(rows) != len(set(x["capability_id"] for x in rows)):
        raise ValueError("HARNESS_DUPLICATED_CAPABILITY")
    focus = {
        "iris": [{"operation": name, "state": status} for name,status in IRIS_SURFACES],
        "rea": [{"operation": name, "state": status} for name,status in REA_SURFACES],
    }
    if rea_probe is not None:
        entries = rea_probe["catalog"]
        for row in focus["rea"]:
            if row["operation"] in ("capability_inventory","provider_inventory","provider_doctor"):
                command = {
                    "capability_inventory": "capabilities",
                    "provider_inventory": "providers",
                    "provider_doctor": "doctor",
                }[row["operation"]]
                if entries[command]["readiness"] == "DISCOVERY_SUCCEEDED":
                    row["state"] = "DISCOVERY_PROBED_NOT_EXECUTION_PROOF"
                else:
                    row["state"] = "DIAGNOSTIC_INCOMPLETE_OR_UNAVAILABLE"
    result = {
        "schema_version": SCHEMA,
        "status": "AUDITED_NOT_PROMOTED",
        "registry_capabilities": rows,
        "registry_total": len(rows),
        "declared_executor_count": sum(x["executor_declared"] for x in rows),
        "runtime_verified_count": 0,
        "focus_surfaces": focus,
        "rea_discovery": rea_probe,
        "selection_policy": "REQUEST_PINNED_AUTHORITY_AND_PROVE_RUNTIME_PER_TASK",
        "capability_autorouting_changed": False,
        "canonical_learning_changed": False,
        "owner_voice_access": "NONE",
        "claims": "Presence, installed CLI, catalog listing and completed task have separate proof boundaries",
    }
    result["evidence_sha256"] = _hash(result)
    return result
