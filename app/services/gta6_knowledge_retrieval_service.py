from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import re
import unicodedata
from typing import Any

from app.database import continuous_operation_repository as continuous_repository
from app.database import gta6_brain_repository as brain_repository
from app.database.memory_claim_repository import get_memory_claim
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import validate_harness_authorization
from app.services.harness_routing_policy_service import HarnessRoutingDecision


KNOWLEDGE_RETRIEVE_CAPABILITY_ID = "gta6.knowledge.retrieve"
KNOWLEDGE_RETRIEVE_EXECUTOR_BINDING = (
    "app.services.gta6_knowledge_retrieval_service.execute_gta6_knowledge_retrieval_capability"
)
DEFAULT_CONTEXT_BYTES = 24 * 1024
MAX_CONTEXT_BYTES = 32 * 1024


def _fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(
        char for char in normalized if not unicodedata.combining(char)
    ).casefold()


def _tokens(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_-]{1,}", _fold(value))
        if token not in {
            "gta", "gta6", "gta-6", "grand", "theft", "auto",
            "sobre", "que", "qual", "quais", "como", "onde", "quando",
            "para", "por", "dos", "das", "uma", "the", "and", "what",
        }
    }


def _source_quality(
    *,
    source_id: str,
    source_url: str,
    source_type: str,
) -> tuple[float, str]:
    source = brain_repository.get_source(source_id)
    authority = str((source or {}).get("authority_class") or "").upper()
    if not authority:
        host = _fold(source_url)
        if "rockstargames.com" in host:
            authority = "ROCKSTAR_OFFICIAL"
        elif "take2games.com" in host:
            authority = "TAKE_TWO_OFFICIAL"
        elif str(source_type).upper() == "PRIMARY_SOURCE":
            authority = "OTHER"
    weights = {
        "ROCKSTAR_OFFICIAL": 1.0,
        "TAKE_TWO_OFFICIAL": 1.0,
        "OFFICIAL_VIDEO": 0.98,
        "OFFICIAL_SOCIAL": 0.95,
        "JOURNALISM": 0.72,
        "DATABASE/REFERENCE": 0.62,
        "COMMUNITY": 0.35,
        "RUMOR": 0.15,
        "OTHER": 0.45,
    }
    if str(source_type).upper() in {"PRIMARY_SOURCE", "OFFICIAL"}:
        return max(0.95, weights.get(authority, 0.0)), authority or "PRIMARY_SOURCE"
    return weights.get(authority, 0.45), authority or "OTHER"


def _freshness(observed_at: Any) -> float:
    try:
        dt = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return 0.5
        days = max(
            0.0,
            (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()
            / 86400.0,
        )
    except (TypeError, ValueError):
        return 0.5
    return round(max(0.15, math.exp(-days / 365.0)), 4)


def _entity_index() -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    entities = {
        str(item["entity_id"]): item
        for item in brain_repository.list_entities(limit=2000)
    }
    graph: dict[str, set[str]] = {}
    for relation in brain_repository.list_relations(limit=4000):
        left = str(relation["subject_id"])
        right = str(relation["object_id"])
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)
    return entities, graph


def _entity_match(
    query_tokens: set[str],
    entity_id: str | None,
    entities: dict[str, dict[str, Any]],
    graph: dict[str, set[str]],
) -> tuple[float, list[str]]:
    if not entity_id or entity_id not in entities or not query_tokens:
        return 0.0, []
    entity = entities[entity_id]
    names = " ".join([
        str(entity.get("canonical_name") or ""),
        *[str(item) for item in entity.get("aliases") or ()],
    ])
    direct_overlap = len(query_tokens & _tokens(names))
    matched = [entity_id] if direct_overlap else []
    score = min(1.0, direct_overlap / max(1, len(query_tokens)))
    for neighbor_id in graph.get(entity_id, set()):
        neighbor = entities.get(neighbor_id)
        if neighbor is None:
            continue
        neighbor_overlap = len(
            query_tokens & _tokens(
                " ".join([
                    str(neighbor.get("canonical_name") or ""),
                    *[str(item) for item in neighbor.get("aliases") or ()],
                ])
            )
        )
        if neighbor_overlap:
            score += min(0.35, 0.15 * neighbor_overlap)
            matched.append(neighbor_id)
    return min(1.0, round(score, 4)), matched


def retrieve_gta6_knowledge(
    *,
    query: str,
    limit: int = 10,
    max_context_bytes: int = DEFAULT_CONTEXT_BYTES,
    include_history: bool = False,
) -> dict[str, Any]:
    text = str(query or "").strip()
    if not text:
        raise ValueError("knowledge retrieval query is required")
    top_k = max(1, min(int(limit), 20))
    byte_budget = max(4096, min(int(max_context_bytes), MAX_CONTEXT_BYTES))
    query_tokens = _tokens(text)

    metadata_by_claim = {
        int(item["claim_id"]): item
        for item in brain_repository.list_claim_metadata(limit=2000)
    }
    entities, graph = _entity_index()
    candidates: list[dict[str, Any]] = []

    for lineage in continuous_repository.list_claim_lineage(limit=500):
        claim_id = int(lineage["claim_id"])
        claim = get_memory_claim(claim_id)
        if claim is None or claim.get("scope") != "gta6":
            continue
        status = str(claim.get("status") or "").casefold()
        if not include_history and status != "active":
            continue
        meta = metadata_by_claim.get(claim_id, {})
        brain_status = str(meta.get("brain_status") or "").upper()
        if not include_history and brain_status not in {"", "ACTIVE", "VERIFIED"}:
            continue

        subject = str(lineage.get("subject") or "")
        content = str(claim.get("claim") or "")
        lexical_overlap = len(
            query_tokens & _tokens(
                " ".join([
                    subject,
                    content,
                    str(lineage.get("source_id") or ""),
                    str(lineage.get("source_url") or ""),
                ])
            )
        )
        lexical = (
            lexical_overlap / max(1, len(query_tokens))
            if query_tokens else 0.0
        )
        entity_score, graph_matches = _entity_match(
            query_tokens,
            meta.get("subject_entity_id"),
            entities,
            graph,
        )
        source_score, authority_class = _source_quality(
            source_id=str(lineage.get("source_id") or ""),
            source_url=str(lineage.get("source_url") or ""),
            source_type=str(lineage.get("source_type") or ""),
        )
        source_id = str(lineage.get("source_id") or "")
        source_state = continuous_repository.get_source_state(source_id) or {}
        source_registry = brain_repository.get_source(source_id) or {}
        confidence = max(
            0.0, min(1.0, float(claim.get("confidence") or 0.0) / 10.0)
        )
        freshness = _freshness(lineage.get("observed_at"))
        novelty = 0.0
        if str(meta.get("knowledge_novelty") or "").upper() == "NEW":
            novelty += 0.5
        if str(meta.get("editorial_novelty") or "").upper() == "UNUSED":
            novelty += 0.5

        hybrid_score = (
            0.44 * min(1.0, lexical)
            + 0.16 * entity_score
            + 0.16 * source_score
            + 0.10 * confidence
            + 0.08 * freshness
            + 0.06 * novelty
        )
        if query_tokens and lexical <= 0 and entity_score <= 0:
            continue
        candidates.append({
            "claim_id": claim_id,
            "subject": subject,
            "claim": content,
            "claim_type": claim.get("claim_type"),
            "status": claim.get("status"),
            "brain_status": brain_status or "ACTIVE",
            "confidence": claim.get("confidence"),
            "source_id": lineage.get("source_id"),
            "source_url": lineage.get("source_url"),
            "source_type": lineage.get("source_type"),
            "authority_class": authority_class,
            "source_fingerprint": source_state.get("content_fingerprint"),
            "source_content_hash": source_registry.get("content_hash"),
            "published_at": lineage.get("published_at"),
            "observed_at": lineage.get("observed_at"),
            "evidence_ref": lineage.get("evidence_ref"),
            "evidence_class": lineage.get("evidence_class"),
            "supersedes_claim_id": lineage.get("supersedes_claim_id"),
            "related_claims": list(lineage.get("related_claims") or ()),
            "subject_entity_id": meta.get("subject_entity_id"),
            "graph_matches": graph_matches,
            "novelty": {
                "world": meta.get("world_novelty") or "UNKNOWN",
                "knowledge": meta.get("knowledge_novelty") or "UNKNOWN",
                "editorial": meta.get("editorial_novelty") or "UNUSED",
            },
            "scores": {
                "lexical": round(min(1.0, lexical), 4),
                "entity_graph": entity_score,
                "source_quality": source_score,
                "confidence": round(confidence, 4),
                "freshness": freshness,
                "novelty": novelty,
                "hybrid": round(hybrid_score, 6),
            },
        })

    candidates.sort(
        key=lambda item: (
            -float(item["scores"]["hybrid"]),
            -float(item["scores"]["source_quality"]),
            str(item.get("observed_at") or ""),
            -int(item["claim_id"]),
        )
    )

    units: list[dict[str, Any]] = []
    used_bytes = 2
    for candidate in candidates:
        if len(units) >= top_k:
            break
        raw = json.dumps(
            candidate,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        if units and used_bytes + len(raw) > byte_budget:
            break
        if len(raw) > byte_budget:
            continue
        units.append(candidate)
        used_bytes += len(raw)

    return {
        "query": text,
        "retrieval_mode": "HYBRID_LEXICAL_GRAPH_QUALITY_TEMPORAL",
        "semantic_embedding_used": False,
        "semantic_embedding_status": "NOT_PROMOTED",
        "candidate_count": len(candidates),
        "knowledge_units": units,
        "context_bytes": used_bytes,
        "max_context_bytes": byte_budget,
        "top_k": top_k,
        "bounded_context": used_bytes <= byte_budget and len(units) <= top_k,
        "source_provenance_preserved": all(
            bool(item.get("evidence_ref") and item.get("source_url"))
            for item in units
        ),
    }


def execute_gta6_knowledge_retrieval_capability(
    *,
    authorization,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
) -> dict[str, Any]:
    auth = validate_harness_authorization(
        authorization,
        expected_action=routing_decision.authorized_action,
        expected_subject=f"capability:{KNOWLEDGE_RETRIEVE_CAPABILITY_ID}",
    )
    if auth.authorized_action not in {"RESEARCH", "EDITORIAL", "DECISION"}:
        raise PermissionError("gta6.knowledge.retrieve requires read-oriented authorization")
    if routing_decision.selected_capability_id != KNOWLEDGE_RETRIEVE_CAPABILITY_ID:
        raise PermissionError("knowledge retrieval capability mismatch")
    if routing_decision.selected_executor_binding != KNOWLEDGE_RETRIEVE_EXECUTOR_BINDING:
        raise PermissionError("knowledge retrieval executor escaped Registry binding")
    record = GLOBAL_CAPABILITY_REGISTRY.get(KNOWLEDGE_RETRIEVE_CAPABILITY_ID)
    if record is None or not record.execution_enabled:
        raise PermissionError("gta6.knowledge.retrieve is not executable")
    result = retrieve_gta6_knowledge(
        query=str(payload.get("query") or ""),
        limit=int(payload.get("limit") or 10),
        max_context_bytes=int(
            payload.get("max_context_bytes") or DEFAULT_CONTEXT_BYTES
        ),
        include_history=bool(payload.get("include_history", False)),
    )
    evidence_refs = list(dict.fromkeys(
        str(item.get("evidence_ref") or "").strip()
        for item in (result.get("knowledge_units") or ())
        if str(item.get("evidence_ref") or "").strip()
    ))
    return {
        "status": "PASS",
        "artifact_ref": f"knowledge-retrieval:{auth.execution_id}",
        "evidence_refs": evidence_refs,
        "authority": auth.authority,
        "authorized_action": auth.authorized_action,
        "provider_calls": 0,
        "canonical_memory_plane": "BR_SQLITE",
        "OBSIDIAN_CANONICAL_MEMORY": "NO",
        "HERMES_DIRECT_CANONICAL_WRITE": "NO",
        "result": result,
    }
