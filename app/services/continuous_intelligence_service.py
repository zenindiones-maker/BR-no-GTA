from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import re
import time
from typing import Any, Mapping

from app.database import continuous_operation_repository as continuous_repository
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
from app.services.harness_authorization_service import validate_harness_authorization
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


def _collect_live(query: str, *, execution_id: str, source_url: str) -> dict[str, Any]:
    if os.getenv("GITHUB_ACTIONS", "").casefold() != "true" and os.getenv(
        "BR_ALLOW_CONTINUOUS_NETWORK_TEST", ""
    ).casefold() not in {"1", "true", "yes"}:
        raise PermissionError("continuous live research may execute only in GitHub Actions")
    from scripts.gta6_fresh_research_worker import collect
    return collect(
        query,
        execution_id=execution_id,
        source_url=source_url,
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
    packet = _collect_live(query, execution_id=auth.execution_id, source_url=source_url)
    latency = max(0.0, time.perf_counter() - started)
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
        "known_state": knowledge_hits,
        "bounded_knowledge_context": bounded,
        "candidate_claims": claims,
        "delta": delta,
        "source_fetch_count": 1 + int(packet.get("official_source_count") or 0),
        "memory_hit_count": len(knowledge_hits),
        "memory_miss_count": int(not knowledge_hits),
        "duplicate_research_avoided": False,
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
    return {
        "claim_id": claim_id,
        "memory_record_id": memory_id,
        "event_id": event_id,
        "lineage": lineage,
        "duplicate": existing is not None,
    }


def gate_verified_gta6_claim(
    *,
    candidate_claim: dict[str, Any],
    fact_check: dict[str, Any],
    source_episode_id: str,
    evaluation_authorization,
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
    if verdict == "SUPPORTED" and source_type == "PRIMARY_SOURCE" and evidence_class == "OFFICIAL":
        decision = "SUPERSEDE" if supersedes_claim_id else "PROMOTE"
        gate = evaluate_memory_candidate(
            memory_id=candidate["memory_id"],
            decision=decision,
            supersedes_memory_id=None,
            reason=(
                "Official primary-source claim passed deterministic provenance-complete fact-check."
            ),
            evidence_refs=(evidence_ref,),
            authorization=evaluation_authorization,
        )
        if decision == "SUPERSEDE":
            # Harness memory supersession is separate from Knowledge Brain claim-id
            # supersession; use PROMOTE here and preserve claim lineage below.
            raise RuntimeError("knowledge claim supersession requires an explicit Harness memory lineage id")
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

    gate = evaluate_memory_candidate(
        memory_id=candidate["memory_id"],
        decision="HUMAN_REVIEW",
        reason=(
            "Non-official, contradicted or insufficient GTA6 claim cannot enter canonical Knowledge Brain automatically."
        ),
        evidence_refs=(evidence_ref,),
        authorization=evaluation_authorization,
    )
    return {
        "status": "HUMAN_REVIEW",
        "candidate": candidate,
        "memory_gate": gate,
        "knowledge": None,
        "GTA6_KNOWLEDGE_PROMOTION_GATE": "PASS",
        "GTA6_CLAIM_PROVENANCE": "PASS",
    }
