"""REA v6 Evidence envelope: bounded technical measurements, no recovered code.

Extract strictly whitelisted numeric metadata from normalized_result.
Untrusted analyzed source is data, never a task instruction or command.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from app.services.reverse_engineering_media_service import ObservationError

MAX_JSON_NODES = 50_000
STAT_FIELDS = (
    "modules", "parsed_javascript_files", "relevant_files", "findings",
    "parse_failures", "invalid_utf8_files", "nested_asar_containers",
    "text_bytes_read", "visited_ast_nodes", "truncated_scopes",
)
SUMMARY_FIELDS = (
    "browser_windows", "context_bridge_apis", "explicit_web_preferences",
    "exposed_api_members", "ipc", "native_addon_bindings",
    "preload_entrypoints", "resolved_native_addon_bindings",
    "resolved_utility_entrypoints", "sender_validation_observations",
    "utility_processes",
)


def _safe_integer(value: Any) -> int | None:
    if type(value) is int and 0 <= value <= 1_000_000_000:
        return value
    if type(value) is float and math.isfinite(value) and value.is_integer() and 0 <= value <= 1_000_000_000:
        return int(value)
    return None


def _safe_collection_length(value: Any) -> int | None:
    if isinstance(value, (list,dict)) and len(value) <= MAX_JSON_NODES:
        return len(value)
    return None


def summarize_rea_javascript_envelope(envelope: Any) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise ObservationError("REA_EVIDENCE_ENVELOPE_SCHEMA_INVALID")
    normalized = envelope.get("normalized_result")
    if not isinstance(normalized, dict):
        return {
            "schema_version":"BRREASafeStructuralEvidence/v1",
            "status":"UNSUPPORTED_OR_UNVERIFIED_ENVELOPE",
            "original_source_code_exposed":False,
            "agent_instructions_from_target":False,
            "quality_approved":False,
        }
    statistics = normalized.get("statistics", {})
    summary = normalized.get("summary", {})
    graph = normalized.get("graph", {})
    semantic = normalized.get("semantic_graph", {})
    if not all(isinstance(x,dict) for x in (statistics,summary,graph,semantic)):
        raise ObservationError("REA_EVIDENCE_METRIC_SCHEMA_INVALID")
    stats = {
        key: number for key in STAT_FIELDS
        if (number := _safe_integer(statistics.get(key))) is not None
    }
    summary_measurements = {
        key: n for key in SUMMARY_FIELDS
        if (n := _safe_collection_length(summary.get(key))) is not None
    }
    graphs = {}
    for key,graph_obj in (("inventory",graph),("semantic",semantic)):
        counts={}
        for name in ("nodes","edges","relations","root_node_ids"):
            n = _safe_collection_length(graph_obj.get(name))
            if n is not None:
                counts[name]=n
        graphs[key]=counts
    limitations = envelope.get("limitations")
    limitation_count = _safe_collection_length(limitations)
    evidence={
        "schema_version":"BRREASafeStructuralEvidence/v1",
        "status":"STRUCTURAL_METRICS_EXTRACTED" if stats or summary_measurements or any(graphs.values())
                 else "NO_VERIFIED_STRUCTURAL_METRICS",
        "measurement_source":"REA_6_NORMALIZED_RESULT",
        "statistics":stats,
        "summary_top_level_collection_lengths":summary_measurements,
        "graph_entry_counts":graphs,
        "reported_limitations_count":limitation_count,
        "no_original_source_recovered_claim":True,
        "native_provider_ready":False,
        "runtime_behavior_observed":False,
        "original_source_code_exposed":False,
        "paths_or_ips_or_urls_exposed":False,
        "agent_instructions_from_target":False,
        "quality_approved":False,
        "limitation":"Only whitelisted numeric metadata; graph elements and recovered code are deliberately excluded",
    }
    evidence["evidence_sha256"]=hashlib.sha256(json.dumps(
        evidence,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False
    ).encode()).hexdigest()
    return evidence
