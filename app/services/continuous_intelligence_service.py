from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import re
import time
from typing import Any, Mapping

from app.database import continuous_operation_repository as continuous_repository
from app.database import gta6_brain_repository as brain_repository
from app.database.memory_claim_evidence_repository import insert_memory_claim_evidence
from app.database.memory_claim_repository import (
    find_memory_claim_by_canonical_key,
    insert_memory_claim,
    update_memory_claim_status,
)
from app.database.memory_event_repository import insert_memory_event
from app.database.memory_record_claims_repository import insert_memory_record_claim
from app.database.memory_repository import insert_memory, update_memory_status
from app.services.bounded_memory_context_service import build_bounded_memory_context
from app.services.continuous_operation_policy_service import load_continuous_operation_policy
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_learning_service import record_memory
from app.services.harness_routing_policy_service import HarnessRoutingDecision
from app.services.memory_claim_evidence_service import create_memory_claim_evidence
from app.services.memory_claim_service import create_memory_claim
from app.services.memory_event_service import create_memory_event
from app.services.memory_service import create_memory
from app.services.memory_plane_service import evaluate_memory_candidate
from app.services.gta6_knowledge_query_service import (
    knowledge_context_to_dict,
    query_gta6_knowledge,
)
from app.services.gta6_source_registry_service import classify_gta6_source


DELTA_RESEARCH_CAPABILITY_ID = "gta6.research.delta"
DELTA_RESEARCH_EXECUTOR_BINDING = (
    "app.services.continuous_intelligence_service.execute_gta6_delta_research_capability"
)

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9'-]{2,}")
_STOP = {
    "what", "has", "have", "the", "about", "including", "and", "from", "with",
    "que", "qual", "quais", "sobre", "como", "para", "dos", "das", "uma", "gta",
    "officially", "confirmed", "rockstar",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_key(url: str) -> str:
    return "source-" + sha256(str(url).strip().encode("utf-8")).hexdigest()[:24]


def _source_domain(url: str) -> str:
    from urllib.parse import urlparse
    return (urlparse(str(url or "")).hostname or "").casefold()


def _entity_type(subject: str) -> str:
    folded = str(subject or "").casefold()
    if any(name in folded for name in ("lucia", "jason")):
        return "CHARACTER"
    if any(name in folded for name in ("vice city", "leonida", "keys")):
        return "LOCATION"
    return "TOPIC"


def _entity_id(entity_type: str, canonical_name: str) -> str:
    identity = f"{entity_type}:{' '.join(str(canonical_name).casefold().split())}"
    return "entity-" + sha256(identity.encode("utf-8")).hexdigest()[:24]


def _raw_evidence_id(source_id: str, content_hash: str) -> str:
    return "evidence-" + sha256(
        f"{source_id}:{content_hash}".encode("utf-8")
    ).hexdigest()[:24]


def _tokens(value: str) -> set[str]:
    return {
        word.casefold()
        for word in _WORD_RE.findall(str(value or ""))
        if word.casefold() not in _STOP
    }


def _fresh_enough(observed_at: str, freshness_seconds: int) -> bool:
    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if observed.tzinfo is None:
        return False
    age = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
    return 0 <= age <= freshness_seconds


def _knowledge_hits(query: str, *, limit: int = 6) -> list[dict[str, Any]]:
    return [
        knowledge_context_to_dict(item)
        for item in query_gta6_knowledge(query=query, limit=limit)
    ]


def _relevant_claims(
    *,
    text: str,
    query: str,
    subject: str,
    source_url: str,
    source_id: str,
    source_type: str,
    observed_at: str,
    published_at: str | None,
    evidence_ref: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    query_tokens = _tokens(query) | _tokens(subject)
    candidates: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for raw in _SENTENCE_RE.split(" ".join(str(text or "").split())):
        sentence = raw.strip()
        if len(sentence) < 25 or len(sentence) > 700:
            continue
        normalized = sentence.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        overlap = len(query_tokens & _tokens(sentence))
        subject_bonus = 4 if _tokens(subject) & _tokens(sentence) else 0
        source_noise_penalty = 2 if sentence.count("Image") > 1 else 0
        score = overlap + subject_bonus - source_noise_penalty
        if score <= 0:
            continue
        candidates.append((score, -len(sentence), sentence))
    candidates.sort(reverse=True)
    result: list[dict[str, Any]] = []
    for _, _, sentence in candidates[:limit]:
        result.append({
            "subject": subject,
            "claim_text": sentence,
            "source_id": source_id,
            "source_url": source_url,
            "source_type": source_type,
            "published_at": published_at,
            "observed_at": observed_at,
            "evidence_ref": evidence_ref,
            "evidence_class": "OFFICIAL" if source_type == "PRIMARY_SOURCE" else "UNVERIFIED",
            "status": "UNVERIFIED",
            "supersedes": None,
            "related_claims": [],
        })
    return result


def _select_primary_source(packet: Mapping[str, Any], requested_url: str) -> dict[str, Any]:
    submitted = packet.get("submitted_source")
    if isinstance(submitted, Mapping) and submitted.get("resolution_status") == "PASS":
        url = str(submitted.get("resolved_url") or submitted.get("url") or "")
        if requested_url and requested_url in {url, str(submitted.get("url") or "")}:
            return {
                "url": url,
                "source_name": str(submitted.get("source_name") or "submitted-official"),
                "source_type": (
                    "PRIMARY_SOURCE"
                    if submitted.get("source_hierarchy") == "OFFICIAL_PRIMARY"
                    else "UNVERIFIED"
                ),
                "content_excerpt": str(submitted.get("content_excerpt") or ""),
                "content_fingerprint": str(submitted.get("content_fingerprint") or ""),
                "content_sha256": str(submitted.get("content_sha256") or ""),
                "observed_at": str(submitted.get("retrieved_at") or packet.get("checked_at") or _now()),
                "published_at": None,
            }
    official = packet.get("official_sources") or ()
    for source in official:
        if not isinstance(source, Mapping):
            continue
        url = str(source.get("resolved_url") or source.get("url") or "")
        if requested_url and requested_url not in {url, str(source.get("url") or "")}:
            continue
        return {
            "url": url,
            "source_name": str(source.get("source_name") or "Rockstar"),
            "source_type": "PRIMARY_SOURCE",
            "content_excerpt": str(source.get("content_excerpt") or ""),
            "content_fingerprint": str(source.get("content_fingerprint") or ""),
            "content_sha256": str(source.get("content_sha256") or ""),
            "observed_at": str(source.get("checked_at") or packet.get("checked_at") or _now()),
            "published_at": source.get("published_at"),
        }
    if official:
        source = dict(official[0])
        return {
            "url": str(source.get("resolved_url") or source.get("url") or ""),
            "source_name": str(source.get("source_name") or "Rockstar"),
            "source_type": "PRIMARY_SOURCE",
            "content_excerpt": str(source.get("content_excerpt") or ""),
            "content_fingerprint": str(source.get("content_fingerprint") or ""),
            "content_sha256": str(source.get("content_sha256") or ""),
            "observed_at": str(source.get("checked_at") or packet.get("checked_at") or _now()),
            "published_at": source.get("published_at"),
        }
    raise RuntimeError("delta research has no primary official source")


def _collect_live(
    query: str,
    *,
    execution_id: str,
    source_url: str,
    source_etag: str = "",
    source_last_modified: str = "",
) -> dict[str, Any]:
    if os.getenv("GITHUB_ACTIONS", "").casefold() != "true" and os.getenv(
        "BR_ALLOW_CONTINUOUS_NETWORK_TEST", ""
    ).casefold() not in {"1", "true", "yes"}:
        raise PermissionError("continuous live research may execute only in GitHub Actions")
    from scripts.gta6_fresh_research_worker import collect
    return collect(
        query,
        execution_id=execution_id,
        source_url=source_url,
        source_etag=source_etag,
        source_last_modified=source_last_modified,
        classification="continuous-intelligence",
        input_kind="scheduled",
    )


def execute_gta6_delta_research_capability(
    *,
    authorization,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
) -> dict[str, Any]:
    auth = validate_harness_authorization(
        authorization,
        expected_action="RESEARCH",
        expected_subject=f"capability:{DELTA_RESEARCH_CAPABILITY_ID}",
    )
    if routing_decision.selected_capability_id != DELTA_RESEARCH_CAPABILITY_ID:
        raise PermissionError("delta research capability mismatch")
    if routing_decision.selected_executor_binding != DELTA_RESEARCH_EXECUTOR_BINDING:
        raise PermissionError("delta research executor escaped Registry binding")

    policy = load_continuous_operation_policy()
    query = str(payload.get("query") or "").strip()
    subject = str(payload.get("subject") or "").strip()
    source_url = str(payload.get("source_url") or "").strip()
    goal_id = str(payload.get("goal_id") or "").strip()
    if not query or not subject or not source_url or not goal_id:
        raise ValueError("delta research requires query, subject, source_url and goal_id")

    freshness = int(policy.resource_governance["source_freshness_seconds"])
    source_key = _source_key(source_url)
    known_source = continuous_repository.get_source_state(source_key)
    bounded = build_bounded_memory_context(
        goal_id=goal_id,
        domain="gta6",
        task_class="continuous-gta6-intelligence",
        capability_id=DELTA_RESEARCH_CAPABILITY_ID,
        agent_id="gta6-research-agent",
        artifact_ref=source_url,
        intent=query,
        max_bytes=int(policy.resource_governance["bounded_memory_bytes"]),
    ).to_dict()
    knowledge_hits = _knowledge_hits(query)
    allow_reuse = bool(payload.get("allow_delta_reuse", True))

    if (
        allow_reuse
        and known_source is not None
        and _fresh_enough(str(known_source.get("observed_at") or ""), freshness)
        and knowledge_hits
    ):
        return {
            "status": "NO_MEANINGFUL_GTA6_DELTA",
            "authority": auth.authority,
            "goal_id": goal_id,
            "query": query,
            "subject": subject,
            "source_url": source_url,
            "source_state": known_source,
            "known_state": knowledge_hits,
            "bounded_knowledge_context": bounded,
            "candidate_claims": [],
            "delta": {
                "NEW_FINDINGS": [],
                "CHANGED_FINDINGS": [],
                "SUPERSEDED_FINDINGS": [],
                "CONTRADICTIONS": [],
                "NO_CHANGE": [source_url],
            },
            "source_fetch_count": 0,
            "memory_hit_count": len(knowledge_hits),
            "memory_miss_count": 0,
            "duplicate_research_avoided": True,
            "SOURCE_UNCHANGED": "YES",
            "LLM_EXTRACTION_SKIPPED": "YES",
            "checked_at": _now(),
            "evidence_refs": [
                str(known_source.get("evidence_ref") or ""),
                *[
                    str(evidence.get("provenance") or "")
                    for item in knowledge_hits
                    for claim in item.get("claims", [])
                    for evidence in claim.get("evidences", [])
                    if str(evidence.get("provenance") or "")
                ],
            ],
        }

    started = time.perf_counter()
    registry_source = brain_repository.get_source(source_key) or {}
    packet = _collect_live(
        query,
        execution_id=auth.execution_id,
        source_url=source_url,
        source_etag=str(registry_source.get("etag") or ""),
        source_last_modified=str(registry_source.get("last_modified") or ""),
    )
    latency = max(0.0, time.perf_counter() - started)
    submitted = packet.get("submitted_source")
    if (
        isinstance(submitted, Mapping)
        and submitted.get("resolution_status") == "NOT_MODIFIED"
    ):
        observed_at = str(packet.get("checked_at") or _now())
        updated_registry = brain_repository.upsert_source({
            **registry_source,
            "source_id": source_key,
            "url": source_url,
            "domain": str(registry_source.get("domain") or _source_domain(source_url)),
            "source_type": str(registry_source.get("source_type") or "PRIMARY_SOURCE"),
            "authority_class": str(
                registry_source.get("authority_class")
                or classify_gta6_source(
                    url=source_url,
                    source_type="PRIMARY_SOURCE",
                ).authority_class
            ),
            "discovered_at": str(
                registry_source.get("discovered_at") or observed_at
            ),
            "last_checked_at": observed_at,
            "last_success_at": observed_at,
            "etag": submitted.get("etag") or registry_source.get("etag"),
            "last_modified": (
                submitted.get("last_modified")
                or registry_source.get("last_modified")
            ),
            "refresh_state": "CURRENT",
            "active": True,
        })
        if known_source is not None:
            continuous_repository.upsert_source_state({
                **known_source,
                "source_key": source_key,
                "source_url": source_url,
                "observed_at": observed_at,
                "etag": updated_registry.get("etag"),
                "last_modified": updated_registry.get("last_modified"),
            })
        return {
            "status": "NO_MEANINGFUL_GTA6_DELTA",
            "authority": auth.authority,
            "goal_id": goal_id,
            "query": query,
            "subject": subject,
            "source_url": source_url,
            "source_state": known_source,
            "source_registry": updated_registry,
            "known_state": knowledge_hits,
            "bounded_knowledge_context": bounded,
            "candidate_claims": [],
            "delta": {
                "NEW_FINDINGS": [],
                "CHANGED_FINDINGS": [],
                "SUPERSEDED_FINDINGS": [],
                "CONTRADICTIONS": [],
                "NO_CHANGE": [source_url],
            },
            "source_fetch_count": 1,
            "memory_hit_count": len(knowledge_hits),
            "memory_miss_count": int(not knowledge_hits),
            "duplicate_research_avoided": True,
            "SOURCE_UNCHANGED": "YES",
            "HTTP_CONDITIONAL_NOT_MODIFIED": "PASS",
            "LLM_EXTRACTION_SKIPPED": "YES",
            "checked_at": observed_at,
            "latency_seconds": latency,
            "evidence_refs": [
                str((known_source or {}).get("evidence_ref") or ""),
            ],
        }
    primary = _select_primary_source(packet, source_url)
    if primary["source_type"] != "PRIMARY_SOURCE":
        raise PermissionError("continuous GTA6 auto-promotion requires an official primary source")
    fingerprint = str(primary.get("content_fingerprint") or "").strip()
    if not fingerprint:
        fingerprint = sha256(primary["content_excerpt"].encode("utf-8")).hexdigest()
    evidence_ref = (
        f"url:{primary['url']}#sha256:"
        + (str(primary.get("content_sha256") or "").strip() or sha256(
            primary["content_excerpt"].encode("utf-8")
        ).hexdigest())
    )
    previous_fingerprint = (
        str(known_source.get("content_fingerprint") or "")
        if known_source is not None else ""
    )
    changed = not previous_fingerprint or previous_fingerprint != fingerprint
    observed_at = str(primary.get("observed_at") or packet.get("checked_at") or _now())
    state = continuous_repository.upsert_source_state({
        "source_key": source_key,
        "source_url": primary["url"],
        "source_type": primary["source_type"],
        "content_fingerprint": fingerprint,
        "observed_at": observed_at,
        "changed_at": (
            observed_at
            if changed or known_source is None
            else str(known_source.get("changed_at") or observed_at)
        ),
        "evidence_ref": evidence_ref,
        "etag": None,
        "last_modified": None,
        "metadata": {
            "source_name": primary.get("source_name"),
            "goal_id": goal_id,
            "query": query,
        },
    })
    source_registry = brain_repository.upsert_source({
        "source_id": source_key,
        "url": primary["url"],
        "domain": _source_domain(primary["url"]),
        "source_type": primary["source_type"],
        "authority_class": classify_gta6_source(
            url=primary["url"],
            source_type=primary["source_type"],
        ).authority_class,
        "reliability_score": classify_gta6_source(
            url=primary["url"],
            source_type=primary["source_type"],
        ).reliability_score,
        "reliability_history": [{
            "observed_at": observed_at,
            "result": "SUCCESS",
            "source_type": primary["source_type"],
        }],
        "discovered_at": (
            str((known_source or {}).get("metadata", {}).get("discovered_at") or observed_at)
        ),
        "last_checked_at": observed_at,
        "last_changed_at": (
            observed_at
            if changed or known_source is None
            else str(known_source.get("changed_at") or observed_at)
        ),
        "last_success_at": observed_at,
        "content_hash": (
            str(primary.get("content_sha256") or "").strip() or fingerprint
        ),
        "etag": (
            (packet.get("submitted_source") or {}).get("etag")
            if isinstance(packet.get("submitted_source"), Mapping)
            else None
        ),
        "last_modified": (
            (packet.get("submitted_source") or {}).get("last_modified")
            if isinstance(packet.get("submitted_source"), Mapping)
            else None
        ),
        "refresh_priority": 100,
        "refresh_interval_seconds": freshness,
        "refresh_state": "CURRENT",
        "active": True,
        "provenance": {
            "evidence_ref": evidence_ref,
            "authority": "DEEPSEEK_HARNESS",
        },
        "metadata": {
            "source_name": primary.get("source_name"),
            "goal_id": goal_id,
            "query": query,
        },
    })
    if known_source is not None and not changed:
        return {
            "status": "NO_MEANINGFUL_GTA6_DELTA",
            "authority": auth.authority,
            "goal_id": goal_id,
            "query": query,
            "subject": subject,
            "source_url": source_url,
            "source_state": state,
            "source_registry": source_registry,
            "known_state": knowledge_hits,
            "bounded_knowledge_context": bounded,
            "candidate_claims": [],
            "delta": {
                "NEW_FINDINGS": [],
                "CHANGED_FINDINGS": [],
                "SUPERSEDED_FINDINGS": [],
                "CONTRADICTIONS": [],
                "NO_CHANGE": [source_url],
            },
            "source_fetch_count": 1,
            "memory_hit_count": len(knowledge_hits),
            "memory_miss_count": int(not knowledge_hits),
            "duplicate_research_avoided": True,
            "SOURCE_UNCHANGED": "YES",
            "LLM_EXTRACTION_SKIPPED": "YES",
            "checked_at": str(packet.get("checked_at") or observed_at),
            "latency_seconds": latency,
            "evidence_refs": [evidence_ref],
        }

    content_hash = (
        str(primary.get("content_sha256") or "").strip()
        or sha256(primary["content_excerpt"].encode("utf-8")).hexdigest()
    )
    raw_evidence, evidence_duplicate = brain_repository.insert_evidence({
        "evidence_id": _raw_evidence_id(source_key, content_hash),
        "source_id": source_key,
        "url": primary["url"],
        "publication_date": primary.get("published_at"),
        "observed_at": observed_at,
        "excerpt": str(primary["content_excerpt"])[:16000],
        "content_hash": content_hash,
        "source_type": primary["source_type"],
        "provenance": {
            "evidence_ref": evidence_ref,
            "authority_class": source_registry["authority_class"],
            "collection": "gta6.research.delta",
        },
        "extraction_method": "direct_source_fetch",
        "metadata": {
            "goal_id": goal_id,
            "query": query,
            "subject": subject,
        },
    })
    claims = _relevant_claims(
        text=primary["content_excerpt"],
        query=query,
        subject=subject,
        source_url=primary["url"],
        source_id=source_key,
        source_type=primary["source_type"],
        observed_at=observed_at,
        published_at=primary.get("published_at"),
        evidence_ref=evidence_ref,
    )
    for claim in claims:
        claim["raw_evidence_id"] = raw_evidence["evidence_id"]
        claim["source_authority_class"] = source_registry["authority_class"]
    if not claims:
        raise RuntimeError("official delta research produced no query-relevant claim candidates")
    delta_key = "NEW_FINDINGS" if known_source is None else (
        "CHANGED_FINDINGS" if changed else "NO_CHANGE"
    )
    delta = {
        "NEW_FINDINGS": claims if delta_key == "NEW_FINDINGS" else [],
        "CHANGED_FINDINGS": claims if delta_key == "CHANGED_FINDINGS" else [],
        "SUPERSEDED_FINDINGS": [],
        "CONTRADICTIONS": [],
        "NO_CHANGE": [source_url] if delta_key == "NO_CHANGE" else [],
    }
    return {
        "status": "PASS",
        "authority": auth.authority,
        "goal_id": goal_id,
        "query": query,
        "subject": subject,
        "source_url": source_url,
        "source_state": state,
        "source_registry": source_registry,
        "raw_evidence": raw_evidence,
        "raw_evidence_duplicate": evidence_duplicate,
        "known_state": knowledge_hits,
        "bounded_knowledge_context": bounded,
        "candidate_claims": claims,
        "delta": delta,
        "source_fetch_count": 1 + int(packet.get("official_source_count") or 0),
        "memory_hit_count": len(knowledge_hits),
        "memory_miss_count": int(not knowledge_hits),
        "duplicate_research_avoided": False,
        "SOURCE_UNCHANGED": "NO",
        "LLM_EXTRACTION_SKIPPED": "NO",
        "checked_at": str(packet.get("checked_at") or observed_at),
        "latency_seconds": latency,
        "evidence_refs": [evidence_ref],
        "packet_summary": {
            "official_source_count": packet.get("official_source_count"),
            "secondary_source_count": packet.get("secondary_source_count"),
            "source_errors": packet.get("source_errors") or [],
        },
    }


def _canonical_claim_key(claim_text: str) -> str:
    return create_memory_claim(
        claim=claim_text,
        claim_type="fact",
        confidence=9.5,
        status="active",
        scope="gta6",
        extraction_method="continuous_gta6_fact_check",
    ).canonical_key


def _ensure_graph_entity(
    *,
    entity_id: str,
    entity_type: str,
    canonical_name: str,
    observed_at: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = brain_repository.get_entity(entity_id)
    return brain_repository.upsert_entity({
        "entity_id": entity_id,
        "entity_type": entity_type,
        "canonical_name": canonical_name,
        "aliases": list((existing or {}).get("aliases") or ()),
        "status": str((existing or {}).get("status") or "ACTIVE"),
        "first_seen_at": str((existing or {}).get("first_seen_at") or observed_at),
        "last_seen_at": observed_at,
        "metadata": {
            **dict((existing or {}).get("metadata") or {}),
            **dict(metadata or {}),
        },
    })


def _record_claim_graph(
    *,
    claim_id: int,
    candidate_claim: dict[str, Any],
    subject_entity_id: str,
    brain_status: str,
    supersedes_claim_id: int | None = None,
    contradicts_claim_ids: tuple[int, ...] = (),
) -> list[str]:
    observed_at = str(candidate_claim["observed_at"])
    claim_entity_id = f"claim-{claim_id}"
    evidence_identity = str(
        candidate_claim.get("raw_evidence_id")
        or candidate_claim.get("evidence_ref")
        or f"claim:{claim_id}:evidence"
    )
    evidence_entity_id = (
        evidence_identity
        if evidence_identity.startswith("evidence-")
        else "evidence-" + sha256(evidence_identity.encode("utf-8")).hexdigest()[:24]
    )
    source_entity_id = "source-entity-" + sha256(
        str(candidate_claim["source_id"]).encode("utf-8")
    ).hexdigest()[:24]

    _ensure_graph_entity(
        entity_id=claim_entity_id,
        entity_type="CLAIM",
        canonical_name=f"Claim {claim_id}",
        observed_at=observed_at,
        metadata={"claim_id": claim_id, "brain_status": brain_status},
    )
    _ensure_graph_entity(
        entity_id=evidence_entity_id,
        entity_type="EVIDENCE",
        canonical_name=f"Evidence {evidence_identity}",
        observed_at=observed_at,
        metadata={
            "evidence_ref": candidate_claim.get("evidence_ref"),
            "raw_evidence_id": candidate_claim.get("raw_evidence_id"),
        },
    )
    _ensure_graph_entity(
        entity_id=source_entity_id,
        entity_type="SOURCE",
        canonical_name=str(candidate_claim["source_id"]),
        observed_at=observed_at,
        metadata={"source_url": candidate_claim.get("source_url")},
    )

    edges = [
        (claim_entity_id, "about", subject_entity_id, claim_id, evidence_entity_id),
        (claim_entity_id, "supported_by", evidence_entity_id, claim_id, evidence_entity_id),
        (evidence_entity_id, "derived_from", source_entity_id, claim_id, evidence_entity_id),
    ]
    if supersedes_claim_id:
        old_entity_id = f"claim-{int(supersedes_claim_id)}"
        _ensure_graph_entity(
            entity_id=old_entity_id,
            entity_type="CLAIM",
            canonical_name=f"Claim {int(supersedes_claim_id)}",
            observed_at=observed_at,
            metadata={"claim_id": int(supersedes_claim_id)},
        )
        edges.append((
            claim_entity_id,
            "supersedes",
            old_entity_id,
            claim_id,
            evidence_entity_id,
        ))
    for other_claim_id in contradicts_claim_ids:
        other_entity_id = f"claim-{int(other_claim_id)}"
        _ensure_graph_entity(
            entity_id=other_entity_id,
            entity_type="CLAIM",
            canonical_name=f"Claim {int(other_claim_id)}",
            observed_at=observed_at,
            metadata={"claim_id": int(other_claim_id)},
        )
        edges.append((
            claim_entity_id,
            "contradicts",
            other_entity_id,
            claim_id,
            evidence_entity_id,
        ))

    relation_ids: list[str] = []
    for subject_id, predicate, object_id, edge_claim_id, evidence_id in edges:
        relation_id = "relation-" + sha256(
            f"{subject_id}:{predicate}:{object_id}:{edge_claim_id}".encode("utf-8")
        ).hexdigest()[:24]
        brain_repository.upsert_relation({
            "relation_id": relation_id,
            "subject_id": subject_id,
            "predicate": predicate,
            "object_id": object_id,
            "claim_id": edge_claim_id,
            "evidence_id": (
                candidate_claim.get("raw_evidence_id")
                if brain_repository.get_evidence(
                    str(candidate_claim.get("raw_evidence_id") or "")
                ) is not None
                else None
            ),
            "confidence": 1.0,
            "status": "ACTIVE",
            "observed_at": observed_at,
            "provenance": {
                "evidence_ref": candidate_claim.get("evidence_ref"),
                "brain_status": brain_status,
            },
            "metadata": {},
        })
        relation_ids.append(relation_id)
    return relation_ids


def _materialize_nonactive_claim(
    *,
    candidate_claim: dict[str, Any],
    fact_check: dict[str, Any],
    brain_status: str,
) -> dict[str, Any]:
    claim_text = str(candidate_claim["claim_text"]).strip()
    canonical_key = _canonical_claim_key(claim_text)
    existing = find_memory_claim_by_canonical_key(canonical_key)
    event = create_memory_event(
        event_type="gta6_claim_review_evidence",
        source_type=str(candidate_claim["source_type"]),
        source_id=str(candidate_claim["source_id"]),
        content=claim_text,
        scope="gta6",
        occurred_at=candidate_claim.get("published_at"),
        observed_at=str(candidate_claim["observed_at"]),
        provenance=str(candidate_claim["evidence_ref"]),
        metadata={
            "source_url": candidate_claim.get("source_url"),
            "fact_check_verdict": fact_check.get("verdict"),
            "brain_status": brain_status,
        },
    )
    event_id = insert_memory_event(event)
    if existing is None:
        claim_id = insert_memory_claim(create_memory_claim(
            claim=claim_text,
            claim_type="fact",
            confidence=min(
                10.0,
                max(0.0, float(fact_check.get("confidence") or 0.0) * 10.0),
            ),
            status="uncertain",
            scope="gta6",
            valid_at=candidate_claim.get("published_at"),
            extraction_method="continuous_gta6_fact_check_review",
        ))
    else:
        claim_id = int(existing["id"])
        if str(existing.get("status") or "").casefold() != "superseded":
            update_memory_claim_status(claim_id, "uncertain")

    insert_memory_claim_evidence(create_memory_claim_evidence(
        claim_id=claim_id,
        event_id=event_id,
        evidence_role=(
            "contradicting"
            if brain_status == "CONTRADICTED"
            else "supporting"
        ),
        weight=min(
            1.0,
            max(0.0, float(fact_check.get("confidence") or 0.0)),
        ),
    ))
    subject_name = str(candidate_claim.get("subject") or "GTA VI").strip()
    subject_entity_id = _entity_id(_entity_type(subject_name), subject_name)
    _ensure_graph_entity(
        entity_id=subject_entity_id,
        entity_type=_entity_type(subject_name),
        canonical_name=subject_name,
        observed_at=str(candidate_claim["observed_at"]),
        metadata={},
    )
    related_claims = tuple(
        int(item)
        for item in candidate_claim.get("related_claims") or ()
        if str(item).isdigit()
    )
    brain_metadata = brain_repository.upsert_claim_metadata({
        "claim_id": claim_id,
        "subject_entity_id": subject_entity_id,
        "predicate": candidate_claim.get("predicate"),
        "object_entity_id": candidate_claim.get("object_entity_id"),
        "brain_status": brain_status,
        "first_seen_at": str(
            (existing or {}).get("created_at")
            or candidate_claim["observed_at"]
        ),
        "last_verified_at": str(candidate_claim["observed_at"]),
        "related_claims": list(related_claims),
        "used_in_content": candidate_claim.get("used_in_content") or [],
        "world_novelty": str(candidate_claim.get("world_novelty") or "UNKNOWN"),
        "knowledge_novelty": "KNOWN" if existing is not None else "NEW",
        "editorial_novelty": str(candidate_claim.get("editorial_novelty") or "UNUSED"),
        "freshness_class": str(candidate_claim.get("freshness_class") or "HIGH"),
        "consolidated_key": canonical_key,
        "metadata": {
            "verification_state": brain_status,
            "fact_check_verdict": fact_check.get("verdict"),
            "fact_check_confidence": fact_check.get("confidence"),
            "raw_evidence_id": candidate_claim.get("raw_evidence_id"),
        },
    })
    lineage = continuous_repository.upsert_claim_lineage({
        "claim_id": claim_id,
        "subject": subject_name,
        "source_id": candidate_claim["source_id"],
        "source_url": candidate_claim["source_url"],
        "source_type": candidate_claim["source_type"],
        "published_at": candidate_claim.get("published_at"),
        "observed_at": candidate_claim["observed_at"],
        "evidence_ref": candidate_claim["evidence_ref"],
        "evidence_class": (
            "CONTRADICTED" if brain_status == "CONTRADICTED" else "UNVERIFIED"
        ),
        "status_snapshot": brain_status,
        "related_claims": list(related_claims),
        "metadata": {
            "fact_check_verdict": fact_check.get("verdict"),
            "nonactive_history": True,
        },
    })
    relations = _record_claim_graph(
        claim_id=claim_id,
        candidate_claim=candidate_claim,
        subject_entity_id=subject_entity_id,
        brain_status=brain_status,
        contradicts_claim_ids=(
            related_claims if brain_status == "CONTRADICTED" else ()
        ),
    )
    return {
        "claim_id": claim_id,
        "event_id": event_id,
        "lineage": lineage,
        "brain_metadata": brain_metadata,
        "subject_entity_id": subject_entity_id,
        "relation_ids": relations,
        "active": False,
    }


def _materialize_knowledge_brain(
    *,
    candidate_claim: dict[str, Any],
    fact_check: dict[str, Any],
    memory_gate: dict[str, Any],
    supersedes_claim_id: int | None = None,
) -> dict[str, Any]:
    claim_text = str(candidate_claim["claim_text"]).strip()
    canonical_key = _canonical_claim_key(claim_text)
    existing = find_memory_claim_by_canonical_key(canonical_key)
    evidence_ref = str(candidate_claim["evidence_ref"])
    event = create_memory_event(
        event_type="gta6_verified_claim",
        source_type=str(candidate_claim["source_type"]),
        source_id=str(candidate_claim["source_id"]),
        content=claim_text,
        scope="gta6",
        occurred_at=candidate_claim.get("published_at"),
        observed_at=str(candidate_claim["observed_at"]),
        provenance=evidence_ref,
        metadata={
            "source_url": candidate_claim["source_url"],
            "evidence_class": candidate_claim["evidence_class"],
            "fact_check_verdict": fact_check.get("verdict"),
            "fact_check_confidence": fact_check.get("confidence"),
            "memory_gate_memory_id": memory_gate["memory"]["memory_id"],
            "supersedes_claim_id": supersedes_claim_id,
        },
    )
    event_id = insert_memory_event(event)
    if existing is None:
        claim = create_memory_claim(
            claim=claim_text,
            claim_type="fact",
            confidence=min(10.0, max(0.0, float(fact_check.get("confidence") or 0.0) * 10.0)),
            status="active",
            scope="gta6",
            valid_at=candidate_claim.get("published_at"),
            extraction_method="continuous_gta6_fact_check",
        )
        claim_id = insert_memory_claim(claim)
        memory_id = insert_memory(create_memory(
            memory_type="semantic",
            content=claim_text,
            source_type=str(candidate_claim["source_type"]),
            source_id=str(candidate_claim["source_id"]),
            confidence=min(10.0, max(0.0, float(fact_check.get("confidence") or 0.0) * 10.0)),
            importance=8.0,
            scope="gta6",
            valid_at=candidate_claim.get("published_at"),
        ))
        insert_memory_record_claim(memory_record_id=memory_id, claim_id=claim_id)
    else:
        claim_id = int(existing["id"])
        from app.database.memory_record_claims_repository import list_memory_records_for_claim
        relations = list_memory_records_for_claim(claim_id, limit=10)
        memory_id = int(relations[0]["memory_record_id"]) if relations else insert_memory(
            create_memory(
                memory_type="semantic",
                content=claim_text,
                source_type=str(candidate_claim["source_type"]),
                source_id=str(candidate_claim["source_id"]),
                confidence=min(10.0, max(0.0, float(fact_check.get("confidence") or 0.0) * 10.0)),
                importance=8.0,
                scope="gta6",
                valid_at=candidate_claim.get("published_at"),
            )
        )
        if not relations:
            insert_memory_record_claim(memory_record_id=memory_id, claim_id=claim_id)

    insert_memory_claim_evidence(create_memory_claim_evidence(
        claim_id=claim_id,
        event_id=event_id,
        evidence_role="supporting",
        weight=min(1.0, max(0.0, float(fact_check.get("confidence") or 0.0))),
    ))
    if supersedes_claim_id:
        update_memory_claim_status(int(supersedes_claim_id), "superseded")
        from app.database.memory_record_claims_repository import list_memory_records_for_claim
        for relation in list_memory_records_for_claim(int(supersedes_claim_id), limit=20):
            update_memory_status(int(relation["memory_record_id"]), "superseded")

    subject_name = str(candidate_claim["subject"]).strip()
    subject_type = str(candidate_claim.get("subject_entity_type") or _entity_type(subject_name))
    subject_entity_id = _entity_id(subject_type, subject_name)
    brain_repository.upsert_entity({
        "entity_id": subject_entity_id,
        "entity_type": subject_type,
        "canonical_name": subject_name,
        "aliases": list(candidate_claim.get("subject_aliases") or ()),
        "status": "ACTIVE",
        "first_seen_at": str(candidate_claim["observed_at"]),
        "last_seen_at": str(candidate_claim["observed_at"]),
        "metadata": {"source_claim_id": claim_id},
    })
    brain_metadata = brain_repository.upsert_claim_metadata({
        "claim_id": claim_id,
        "subject_entity_id": subject_entity_id,
        "predicate": candidate_claim.get("predicate"),
        "object_entity_id": candidate_claim.get("object_entity_id"),
        "brain_status": "ACTIVE",
        "first_seen_at": (
            str(existing.get("created_at"))
            if existing is not None and existing.get("created_at")
            else str(candidate_claim["observed_at"])
        ),
        "last_verified_at": str(candidate_claim["observed_at"]),
        "superseded_by_claim_id": None,
        "related_claims": candidate_claim.get("related_claims") or [],
        "used_in_content": candidate_claim.get("used_in_content") or [],
        "world_novelty": str(candidate_claim.get("world_novelty") or "UNKNOWN"),
        "knowledge_novelty": "KNOWN" if existing is not None else "NEW",
        "editorial_novelty": str(candidate_claim.get("editorial_novelty") or "UNUSED"),
        "freshness_class": str(candidate_claim.get("freshness_class") or "HIGH"),
        "freshness_due_at": candidate_claim.get("freshness_due_at"),
        "consolidated_key": canonical_key,
        "metadata": {
            "verification_state": "VERIFIED",
            "fact_check_verdict": fact_check.get("verdict"),
            "fact_check_confidence": fact_check.get("confidence"),
            "raw_evidence_id": candidate_claim.get("raw_evidence_id"),
            "source_authority_class": candidate_claim.get("source_authority_class"),
        },
    })
    if supersedes_claim_id:
        previous_meta = brain_repository.get_claim_metadata(int(supersedes_claim_id))
        if previous_meta is not None:
            brain_repository.upsert_claim_metadata({
                **previous_meta,
                "brain_status": "SUPERSEDED",
                "superseded_by_claim_id": claim_id,
                "last_verified_at": str(candidate_claim["observed_at"]),
            })

    lineage = continuous_repository.upsert_claim_lineage({
        "claim_id": claim_id,
        "subject": candidate_claim["subject"],
        "source_id": candidate_claim["source_id"],
        "source_url": candidate_claim["source_url"],
        "source_type": candidate_claim["source_type"],
        "published_at": candidate_claim.get("published_at"),
        "observed_at": candidate_claim["observed_at"],
        "evidence_ref": evidence_ref,
        "evidence_class": candidate_claim["evidence_class"],
        "status_snapshot": "ACTIVE",
        "supersedes_claim_id": supersedes_claim_id,
        "related_claims": candidate_claim.get("related_claims") or [],
        "metadata": {
            "memory_record_id": memory_id,
            "memory_gate_memory_id": memory_gate["memory"]["memory_id"],
            "fact_check_verdict": fact_check.get("verdict"),
        },
    })
    relation_ids = _record_claim_graph(
        claim_id=claim_id,
        candidate_claim=candidate_claim,
        subject_entity_id=subject_entity_id,
        brain_status="ACTIVE",
        supersedes_claim_id=supersedes_claim_id,
    )
    return {
        "claim_id": claim_id,
        "memory_record_id": memory_id,
        "event_id": event_id,
        "lineage": lineage,
        "brain_metadata": brain_metadata,
        "subject_entity_id": subject_entity_id,
        "relation_ids": relation_ids,
        "duplicate": existing is not None,
    }


def gate_verified_gta6_claim(
    *,
    candidate_claim: dict[str, Any],
    fact_check: dict[str, Any],
    source_episode_id: str,
    evaluation_authorization=None,
    supersedes_claim_id: int | None = None,
) -> dict[str, Any]:
    verdict = str(fact_check.get("verdict") or "")
    source_type = str(candidate_claim.get("source_type") or "")
    evidence_class = str(candidate_claim.get("evidence_class") or "")
    evidence_ref = str(candidate_claim.get("evidence_ref") or "")
    if not evidence_ref or not source_episode_id:
        raise ValueError("knowledge candidate requires episode and evidence lineage")
    candidate = record_memory(
        memory_type="SEMANTIC",
        claim=str(candidate_claim["claim_text"]),
        domain="gta6",
        task_class="continuous-gta6-intelligence",
        source_episode_ids=(source_episode_id,),
        evidence_refs=(evidence_ref,),
        agent_id="gta6-fact-check",
        capability_id="gta6.fact-check",
        metadata={
            "memory_class": "KNOWLEDGE_MEMORY",
            "subject": candidate_claim.get("subject"),
            "source_id": candidate_claim.get("source_id"),
            "source_url": candidate_claim.get("source_url"),
            "source_type": source_type,
            "evidence_class": evidence_class,
            "published_at": candidate_claim.get("published_at"),
            "observed_at": candidate_claim.get("observed_at"),
            "supersedes_claim_id": supersedes_claim_id,
            "evaluation_required": True,
            "canonical_auto_promotion": False,
        },
        confidence=min(1.0, max(0.0, float(fact_check.get("confidence") or 0.0))),
        status="CANDIDATE",
        identity_payload={
            "claim": str(candidate_claim["claim_text"]),
            "source": candidate_claim.get("source_id"),
            "episode": source_episode_id,
        },
    )
    owned_authorization = False
    if evaluation_authorization is None:
        evaluation_authorization = issue_harness_authorization(
            authorized_action="DECISION",
            subject=f"learning:memory:{candidate['memory_id']}",
            harness_decision_id=f"decision-knowledge-{candidate['memory_id'][-16:]}",
            execution_id=f"execution-knowledge-{candidate['memory_id'][-16:]}",
            lineage={
                "memory_id": candidate["memory_id"],
                "source_episode_id": source_episode_id,
                "subject": candidate_claim.get("subject"),
                "authority": "DEEPSEEK_HARNESS",
            },
        )
        owned_authorization = True

    source_policy = classify_gta6_source(
        url=str(candidate_claim.get("source_url") or ""),
        source_type=source_type,
    )
    official_authority = source_policy.authority_class in {
        "ROCKSTAR_OFFICIAL",
        "TAKE_TWO_OFFICIAL",
        "OFFICIAL_VIDEO",
        "OFFICIAL_SOCIAL",
    }
    primary_evidence_policy = (
        source_type == "PRIMARY_SOURCE"
        and evidence_class == "OFFICIAL"
        and official_authority
    )

    if verdict == "SUPPORTED" and primary_evidence_policy:
        # The Knowledge Brain claim lineage has its own immutable claim-id
        # supersession chain. Harness memory promotion remains a normal PROMOTE
        # gate so the two identity namespaces are never conflated.
        gate = evaluate_memory_candidate(
            memory_id=candidate["memory_id"],
            decision="PROMOTE",
            reason=(
                "Official primary-source claim passed deterministic provenance-complete fact-check."
            ),
            evidence_refs=(evidence_ref,),
            authorization=evaluation_authorization,
        )
        knowledge = _materialize_knowledge_brain(
            candidate_claim=candidate_claim,
            fact_check=fact_check,
            memory_gate=gate,
            supersedes_claim_id=supersedes_claim_id,
        )
        return {
            "status": "PROMOTED",
            "candidate": candidate,
            "memory_gate": gate,
            "knowledge": knowledge,
            "GTA6_KNOWLEDGE_PROMOTION_GATE": "PASS",
            "GTA6_CLAIM_PROVENANCE": "PASS",
        }

    if not primary_evidence_policy:
        gate = evaluate_memory_candidate(
            memory_id=candidate["memory_id"],
            decision="HUMAN_REVIEW",
            reason=(
                "Non-primary/community/rumor evidence is signal-only and cannot "
                "materialize canonical GTA6 Knowledge without eligible primary evidence."
            ),
            evidence_refs=(evidence_ref,),
            authorization=evaluation_authorization,
        )
        review_status = (
            "REJECTED"
            if source_type in {"RUMOR"}
            or evidence_class in {"RUMOR"}
            or source_policy.authority_class == "RUMOR"
            else "UNVERIFIED"
        )
        return {
            "status": "HUMAN_REVIEW",
            "candidate": candidate,
            "memory_gate": gate,
            "knowledge": None,
            "brain_status": review_status,
            "source_policy": {
                "authority_class": source_policy.authority_class,
                "primary_evidence_policy": False,
            },
            "canonical_materialized": False,
            "GTA6_KNOWLEDGE_PROMOTION_GATE": "PASS",
            "GTA6_CLAIM_PROVENANCE": "PASS",
        }

    gate = evaluate_memory_candidate(
        memory_id=candidate["memory_id"],
        decision="HUMAN_REVIEW",
        reason=(
            "Non-official, contradicted or insufficient GTA6 claim cannot enter active canonical knowledge automatically."
        ),
        evidence_refs=(evidence_ref,),
        authorization=evaluation_authorization,
    )
    review_status = (
        "CONTRADICTED"
        if verdict in {"CONTRADICTED", "CONFLICTING_EVIDENCE"}
        else "UNVERIFIED"
    )
    historical = _materialize_nonactive_claim(
        candidate_claim=candidate_claim,
        fact_check=fact_check,
        brain_status=review_status,
    )
    return {
        "status": "HUMAN_REVIEW",
        "candidate": candidate,
        "memory_gate": gate,
        "knowledge": historical,
        "brain_status": review_status,
        "GTA6_KNOWLEDGE_PROMOTION_GATE": "PASS",
        "GTA6_CLAIM_PROVENANCE": "PASS",
    }
