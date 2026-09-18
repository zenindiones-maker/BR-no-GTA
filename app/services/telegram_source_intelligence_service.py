from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import re
from typing import Any
from urllib.parse import urlparse

from app.database import telegram_source_intelligence_repository as source_repository
from app.database.editorial_repository import list_evaluations_for_research
from app.database.gta6_goal_repository import (
    get_active_gta6_goal,
    get_gta6_goal_artifacts_by_idea_id,
)
from app.database.memory_claim_evidence_repository import (
    insert_memory_claim_evidence,
    list_memory_claim_evidence_for_event,
)
from app.database.memory_claim_repository import (
    find_memory_claim_by_canonical_key,
    insert_memory_claim,
    update_memory_claim_status,
)
from app.database.memory_event_repository import insert_memory_event
from app.database.memory_repository import find_memory_by_source, update_memory_status
from app.database.telegram_user_input_repository import update_telegram_source_state
from app.database.harness_authorization_repository import get_harness_authorization
from app.services.editorial_intelligence_contracts import (
    ClaimLedgerItem,
    ResearchDossier,
    ResearchSource,
    validate_claim_ledger,
)
from app.integrations.gta6.source import GTA6SourceItem
from app.services.gta6_editorial_pipeline import process_gta6_research_results
from app.services.gta6_fact_check_service import execute_gta6_fact_check_via_harness
from app.services.gta6_ingestion import ingest_gta6_source_item
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.memory_claim_evidence_service import create_memory_claim_evidence
from app.services.memory_claim_service import create_memory_claim
from app.services.memory_consolidation_persistence_service import consolidate_and_persist_claim
from app.services.memory_event_service import create_memory_event


FACT_CHECK_TASK_CLASS = "telegram-source-fact-check"
EDITORIAL_TASK_CLASS = "telegram-source-editorial-signal"
EDITORIAL_CAPABILITY_ID = "editorial.process"
FACT_CHECK_CAPABILITY_ID = "gta6.fact-check"

SOURCE_HIERARCHY = {
    "OFFICIAL_PRIMARY",
    "PRIMARY_STATEMENT_REPORTED_BY_SECONDARY",
    "MULTIPLE_INDEPENDENT_REPORTS",
    "SECONDARY_REPORT",
    "COMMUNITY_SIGNAL",
    "INSUFFICIENT_EVIDENCE",
}


def _stable(prefix: str, value: str) -> str:
    return f"{prefix}-" + sha256(value.encode("utf-8")).hexdigest()[:24]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _words(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9à-ÿ]+", str(value or "").casefold())
        if len(token) >= 4
    }


def _overlap(statement: str, evidence: str) -> float:
    claim = _words(statement)
    if not claim:
        return 0.0
    observed = _words(evidence)
    return len(claim & observed) / len(claim)


def _extract_claims(text: str, *, limit: int = 4) -> list[str]:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    gta_terms = (
        "gta", "grand theft auto", "rockstar", "take-two", "take two",
        "lucia", "jason", "vice city", "leonida",
    )
    selected: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 35 or len(sentence) > 600:
            continue
        folded = sentence.casefold()
        if not any(term in folded for term in gta_terms):
            continue
        if sentence not in selected:
            selected.append(sentence)
        if len(selected) >= limit:
            break
    return selected


def _research_sources(packet: dict[str, Any]) -> tuple[ResearchSource, ...]:
    sources: list[ResearchSource] = []
    seen_urls: set[str] = set()

    submitted = packet.get("submitted_source")
    if isinstance(submitted, dict) and submitted.get("resolution_status") == "PASS":
        url = str(submitted.get("resolved_url") or submitted.get("url") or "")
        if url:
            seen_urls.add(url)
            sources.append(
                ResearchSource(
                    source_id=_stable("source", url),
                    url=url,
                    source_type="submitted",
                    source_authority=str(submitted.get("source_hierarchy") or "SECONDARY_REPORT"),
                    original_source=True,
                    retrieved_at=str(submitted.get("retrieved_at") or packet.get("checked_at") or _now()),
                    title=str(submitted.get("source_name") or "") or None,
                    independent_group=str(submitted.get("independent_group") or "") or None,
                    provenance={
                        "source": "telegram_submitted_url",
                        "content_sha256": submitted.get("content_sha256"),
                        "content_fingerprint": submitted.get("content_fingerprint"),
                        "original_source_retrieved": True,
                    },
                )
            )

    for item in packet.get("official_sources") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("resolved_url") or item.get("url") or "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        sources.append(
            ResearchSource(
                source_id=_stable("source", url),
                url=url,
                source_type="official",
                source_authority="OFFICIAL_PRIMARY",
                original_source=True,
                retrieved_at=str(item.get("checked_at") or packet.get("checked_at") or _now()),
                title=str(item.get("source_name") or "") or None,
                independent_group=str(item.get("independent_group") or "") or None,
                provenance={
                    "source": "fresh_research",
                    "content_fingerprint": item.get("content_fingerprint"),
                    "original_source_retrieved": True,
                },
            )
        )

    for item in packet.get("secondary_sources") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if not url or not url.startswith("https://") or url in seen_urls:
            continue
        seen_urls.add(url)
        hierarchy = str(item.get("source_hierarchy") or "SECONDARY_REPORT")
        if hierarchy not in SOURCE_HIERARCHY:
            hierarchy = "SECONDARY_REPORT"
        sources.append(
            ResearchSource(
                source_id=_stable("source", url),
                url=url,
                source_type="community" if hierarchy == "COMMUNITY_SIGNAL" else "secondary",
                source_authority=hierarchy,
                original_source=False,
                retrieved_at=str(packet.get("checked_at") or _now()),
                published_at=str(item.get("published_at") or "") or None,
                title=str(item.get("title") or item.get("source_name") or "") or None,
                independent_group=str(item.get("independent_group") or "") or None,
                community_source=hierarchy == "COMMUNITY_SIGNAL",
                provenance={
                    "source": "fresh_research",
                    "content_fingerprint": item.get("content_fingerprint"),
                    "original_source_retrieved": False,
                },
            )
        )
    return tuple(sources)


def _dossier(
    *,
    candidate: dict[str, Any],
    input_record: dict[str, Any],
    packet: dict[str, Any],
    execution_id: str,
) -> ResearchDossier | None:
    sources = _research_sources(packet)
    if len(sources) < 3:
        return None
    submitted = packet.get("submitted_source")
    submitted_text = (
        str(submitted.get("content_excerpt") or "")
        if isinstance(submitted, dict) and submitted.get("resolution_status") == "PASS"
        else ""
    )
    claims = tuple(_extract_claims(submitted_text))
    dossier_id = _stable(
        "dossier",
        f"{candidate['candidate_id']}:{execution_id}:{packet.get('checked_at')}",
    )
    return ResearchDossier(
        mission_id=dossier_id,
        goal_id=f"source-candidate:{candidate['candidate_id']}",
        research_execution_id=execution_id,
        research_cutoff_timestamp=str(packet.get("checked_at") or _now()),
        research_questions=(
            "What claims does the submitted source make?",
            "Which claims have direct official support or independent corroboration?",
            "Is the source suitable for semantic memory or editorial use?",
        ),
        queries=(str(input_record.get("text_content") or candidate["source_url"]),),
        sources=sources,
        claims_extracted=claims,
        supporting_evidence=(),
        contradicting_evidence=(),
        historical_changes=(),
        discarded_claims=(),
        provenance={
            "source": "telegram",
            "telegram_input_id": input_record["id"],
            "memory_event_id": input_record.get("memory_event_id"),
            "source_candidate_id": candidate["candidate_id"],
            "fresh_research_execution_id": execution_id,
        },
    )


def _evidence_for_claim(
    statement: str,
    packet: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    official_support = False
    secondary_groups: set[str] = set()
    fingerprints: set[str] = set()

    submitted = packet.get("submitted_source")
    if isinstance(submitted, dict) and submitted.get("resolution_status") == "PASS":
        hierarchy = str(submitted.get("source_hierarchy") or "SECONDARY_REPORT")
        excerpt = str(submitted.get("content_excerpt") or "")
        supports = _overlap(statement, excerpt) >= 0.55
        stance = "supporting" if supports and hierarchy == "OFFICIAL_PRIMARY" else "context"
        weight = 1.0 if stance == "supporting" else 0.0
        official_support = stance == "supporting"
        evidence.append(
            {
                "evidence_id": _stable("evidence", f"submitted:{submitted.get('url')}:{statement}"),
                "source_ref": str(submitted.get("url")),
                "stance": stance,
                "weight": weight,
                "excerpt": excerpt[:900],
                "provenance": {
                    "url": submitted.get("url"),
                    "retrieved_at": submitted.get("retrieved_at"),
                    "source_hierarchy": hierarchy,
                    "original_source_retrieved": True,
                    "content_sha256": submitted.get("content_sha256"),
                },
            }
        )

    for item in packet.get("official_sources") or []:
        if not isinstance(item, dict):
            continue
        excerpt = str(item.get("content_excerpt") or "")
        if _overlap(statement, excerpt) < 0.55:
            continue
        official_support = True
        evidence.append(
            {
                "evidence_id": _stable("evidence", f"official:{item.get('url')}:{statement}"),
                "source_ref": str(item.get("url")),
                "stance": "supporting",
                "weight": 1.0,
                "excerpt": excerpt[:900],
                "provenance": {
                    "url": item.get("url"),
                    "retrieved_at": item.get("checked_at") or packet.get("checked_at"),
                    "source_hierarchy": "OFFICIAL_PRIMARY",
                    "original_source_retrieved": True,
                },
            }
        )

    for item in packet.get("secondary_sources") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("source_hierarchy") or "") == "COMMUNITY_SIGNAL":
            continue
        excerpt = f"{item.get('title') or ''} {item.get('summary') or ''}".strip()
        if _overlap(statement, excerpt) < 0.55:
            continue
        group = str(item.get("independent_group") or "").strip()
        fingerprint = str(item.get("content_fingerprint") or "").strip()
        if not group or not fingerprint or fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        secondary_groups.add(group)
        evidence.append(
            {
                "evidence_id": _stable("evidence", f"secondary:{item.get('url')}:{statement}"),
                "source_ref": str(item.get("url")),
                "stance": "supporting",
                "weight": 0.7,
                "excerpt": excerpt[:900],
                "provenance": {
                    "url": item.get("url"),
                    "published_at": item.get("published_at") or packet.get("checked_at"),
                    "source_hierarchy": "SECONDARY_REPORT",
                    "independent_group": group,
                    "content_fingerprint": fingerprint,
                    "original_source_retrieved": False,
                },
            }
        )

    return evidence, {
        "official_support": official_support,
        "independent_secondary_groups": sorted(secondary_groups),
        "independent_secondary_count": len(secondary_groups),
    }


def _fact_check(
    *,
    candidate: dict[str, Any],
    input_record: dict[str, Any],
    statement: str,
    index: int,
    evidence: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="fact-check a claim extracted from one resolved Telegram source",
            authorized_action="RESEARCH",
            domain="research",
            task_class=FACT_CHECK_TASK_CLASS,
            goal_id=f"source-candidate:{candidate['candidate_id']}",
            required_capability_id=FACT_CHECK_CAPABILITY_ID,
            required_policy_tags=("gta6", "fact", "check", "evidence"),
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="RESEARCH",
        subject=f"capability:{FACT_CHECK_CAPABILITY_ID}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "ingress": "telegram",
            "telegram_input_id": input_record["id"],
            "memory_event_id": input_record.get("memory_event_id"),
            "source_candidate_id": candidate["candidate_id"],
            "source_url": candidate["source_url"],
        },
    )
    payload = {
        "claim": statement,
        "mission_id": f"telegram-source:{candidate['candidate_id']}",
        "task_id": f"claim-{index + 1}",
        "goal_id": f"source-candidate:{candidate['candidate_id']}",
        "input_refs": [
            f"telegram-input:{input_record['id']}",
            f"memory-event:{input_record.get('memory_event_id')}",
            f"source-candidate:{candidate['candidate_id']}",
        ],
        "evidence": evidence,
    }
    try:
        canonical = execute_gta6_fact_check_via_harness(
            authorization=authorization,
            routing_decision=routing,
            payload=payload,
        )
    finally:
        consume_harness_authorization(authorization)
    if not canonical.success or not isinstance(canonical.result, dict):
        raise RuntimeError("gta6.fact-check failed for Telegram source claim")
    fact_check = canonical.result.get("fact_check")
    if not isinstance(fact_check, dict):
        raise RuntimeError("gta6.fact-check result is missing")
    return fact_check, {
        "routing_id": routing.routing_id,
        "authorization_id": authorization.authorization_id,
        "execution_id": authorization.execution_id,
        "telegram_input_id": input_record["id"],
        "memory_event_id": input_record.get("memory_event_id"),
        "source_candidate_id": candidate["candidate_id"],
        "source_url": candidate["source_url"],
        "canonical_result": canonical.to_dict(),
    }


def _promote_verified_claim(
    *,
    candidate: dict[str, Any],
    input_record: dict[str, Any],
    statement: str,
    fact_check: dict[str, Any],
    hierarchy: str,
    evidence_refs: list[str],
) -> int:
    event = create_memory_event(
        event_type="telegram_source_verified_claim",
        source_type="telegram_source_intelligence",
        source_id=candidate["candidate_id"],
        content=statement,
        scope="gta6",
        provenance="telegram_source_fact_checked",
        metadata={
            "telegram_input_id": input_record["id"],
            "memory_event_id": input_record.get("memory_event_id"),
            "source_url": candidate["source_url"],
            "source_hierarchy": hierarchy,
            "fact_check_result": fact_check.get("verdict"),
            "fact_check_checked_at": fact_check.get("checked_at"),
            "evidence_refs": evidence_refs,
        },
    )
    event_id = insert_memory_event(event)
    confidence = 10.0 if hierarchy == "OFFICIAL_PRIMARY" else 8.5
    claim = create_memory_claim(
        claim=statement,
        claim_type="observation",
        confidence=confidence,
        status="active",
        scope="gta6",
        extraction_method="telegram_source_fact_checked",
    )
    existing = find_memory_claim_by_canonical_key(claim.canonical_key)
    claim_id = int(existing["id"]) if existing is not None else insert_memory_claim(claim)
    already_linked = any(
        int(item["claim_id"]) == claim_id
        for item in list_memory_claim_evidence_for_event(event_id)
    )
    if not already_linked:
        insert_memory_claim_evidence(
            create_memory_claim_evidence(
                claim_id=claim_id,
                event_id=event_id,
                evidence_role="supporting",
                weight=1.0,
            )
        )
    memories = find_memory_by_source(source_type="memory_claim", source_id=str(claim_id))
    if memories:
        return int(memories[0]["id"])
    return int(consolidate_and_persist_claim(claim_id)["memory_id"])


def _claim_ledger(
    *,
    dossier: ResearchDossier | None,
    claims: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if dossier is None or not claims:
        return []
    by_url = {source.url: source.source_id for source in dossier.sources}
    items: list[ClaimLedgerItem] = []
    for claim in claims:
        payload = dict(claim.get("payload") or {})
        fact_check = dict(payload.get("fact_check") or {})
        source_ids = tuple(
            dict.fromkeys(
                by_url[url]
                for url in (fact_check.get("source_refs") or ())
                if url in by_url
            )
        )
        verification = str(claim.get("verification_status") or "")
        hierarchy = str(claim.get("source_hierarchy") or "")
        if verification == "CONTRADICTED":
            classification = "CONTRADICTED"
        elif hierarchy == "OFFICIAL_PRIMARY":
            classification = "OFFICIAL_CONFIRMED"
        elif hierarchy == "MULTIPLE_INDEPENDENT_REPORTS":
            classification = "MULTIPLE_REPUTABLE_REPORTS"
        else:
            classification = "INSUFFICIENT_EVIDENCE"
        fact_result = str(fact_check.get("verdict") or "INSUFFICIENT_EVIDENCE")
        if fact_result not in {
            "SUPPORTED", "CONTRADICTED", "CONFLICTING_EVIDENCE",
            "INSUFFICIENT_EVIDENCE",
        }:
            fact_result = "INSUFFICIENT_EVIDENCE"
        approved = verification == "VERIFIED" and fact_result == "SUPPORTED"
        items.append(
            ClaimLedgerItem(
                claim_id=str(claim["claim_id"]),
                statement=str(claim["statement"]),
                classification=classification,
                source_refs=source_ids,
                supporting_evidence_refs=(
                    source_ids if fact_result == "SUPPORTED" else ()
                ),
                contradicting_evidence_refs=(
                    source_ids if fact_result == "CONTRADICTED" else ()
                ),
                confidence=float(fact_check.get("confidence") or 0.0),
                fact_check_result=fact_result,
                provenance={
                    "source_candidate_id": claim["candidate_id"],
                    "source_hierarchy": hierarchy,
                    "fact_check_lineage": payload.get("fact_check_lineage") or {},
                    "evidence_refs": claim.get("evidence_refs") or [],
                },
                script_usage="NOT_USED",
                final_status=(
                    "APPROVED_FOR_SCRIPT" if approved else "REJECTED_FROM_SCRIPT"
                ),
            )
        )
    validate_claim_ledger(
        items,
        known_source_refs=(source.source_id for source in dossier.sources),
    )
    return [item.to_dict() for item in items]


def _editorial_decision(
    *,
    candidate: dict[str, Any],
    input_record: dict[str, Any],
    claims: list[dict[str, Any]],
    dossier_id: str | None,
) -> dict[str, Any]:
    existing = source_repository.get_editorial_signal_by_candidate(
        candidate["candidate_id"]
    )
    if existing is not None:
        return existing

    verified = [item for item in claims if item["verification_status"] == "VERIFIED"]
    text = str(input_record.get("text_content") or "").casefold()
    explicit_video_intent = any(
        marker in text
        for marker in ("video", "vídeo", "pauta", "transforma", "transforme")
    )

    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=(
                "evaluate a verified Telegram source as an editorial signal "
                "without automatically dispatching production"
            ),
            authorized_action="EDITORIAL",
            domain="editorial",
            task_class=EDITORIAL_TASK_CLASS,
            goal_id=f"source-candidate:{candidate['candidate_id']}",
            required_capability_id=EDITORIAL_CAPABILITY_ID,
            required_policy_tags=("editorial", "queue", "gta6"),
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject=f"capability:{EDITORIAL_CAPABILITY_ID}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "ingress": "telegram",
            "telegram_input_id": input_record["id"],
            "memory_event_id": input_record.get("memory_event_id"),
            "source_candidate_id": candidate["candidate_id"],
            "research_dossier_id": dossier_id,
            "verified_claim_ids": [item["claim_id"] for item in verified],
            "explicit_video_intent": explicit_video_intent,
        },
    )

    decision = "REJECT_LOW_EVIDENCE"
    signal_status = "CREATED"
    goal_id = None
    pipeline_result: dict[str, Any] | None = None
    research_item_id = None
    knowledge_id = None

    try:
        if not verified:
            decision = "REJECT_LOW_EVIDENCE"
        elif not explicit_video_intent:
            decision = "STORE_FOR_FUTURE"
        else:
            title = str(verified[0]["statement"]).strip()[:240]
            existing_goal = get_active_gta6_goal(topic=title)
            if existing_goal is not None:
                decision = "MERGE_WITH_EXISTING_GOAL"
                goal_id = existing_goal["goal_id"]
                signal_status = "USED"
            else:
                packet = dict((candidate.get("payload") or {}).get("fresh_packet") or {})
                submitted = dict(packet.get("submitted_source") or {})
                source_name = str(
                    submitted.get("source_name")
                    or urlparse(candidate["source_url"]).hostname
                    or "telegram-source"
                )
                published_at = (
                    str(submitted.get("retrieved_at") or "").strip() or None
                )
                source_item = GTA6SourceItem(
                    title=title,
                    summary=" ".join(
                        str(item["statement"]).strip()
                        for item in verified
                    ),
                    url=candidate["source_url"],
                    source_name=source_name,
                    fact_type="news",
                    confidence="confirmed",
                    published_at=published_at,
                )
                ingested = ingest_gta6_source_item(source_item)
                research_item_id = int(ingested["research_item_id"])
                knowledge_id = int(ingested["knowledge_id"])
                processed = process_gta6_research_results([ingested])
                if processed:
                    pipeline_result = dict(processed[0])
                else:
                    evaluations = list_evaluations_for_research(research_item_id)
                    if evaluations:
                        latest = dict(evaluations[-1])
                        pipeline_result = {
                            "evaluation_id": latest.get("id"),
                            "research_item_id": research_item_id,
                            "idea_id": latest.get("idea_id"),
                            "score": latest.get("score"),
                            "decision": latest.get("decision"),
                            "criteria": {
                                "novelty": latest.get("novelty"),
                                "source_reliability": latest.get("source_reliability"),
                            },
                        }
                if pipeline_result is None:
                    decision = "STORE_FOR_FUTURE"
                else:
                    pipeline_decision = str(
                        pipeline_result.get("decision") or ""
                    ).lower()
                    if pipeline_decision == "approve":
                        decision = "USE_FOR_VIDEO"
                    elif pipeline_decision == "discard" and float(
                        (pipeline_result.get("criteria") or {}).get("novelty") or 0.0
                    ) < 5.0:
                        decision = "REJECT_SATURATED"
                    else:
                        decision = "STORE_FOR_FUTURE"
                    idea_id = pipeline_result.get("idea_id")
                    if isinstance(idea_id, int) and idea_id > 0:
                        artifacts = get_gta6_goal_artifacts_by_idea_id(idea_id)
                        if artifacts is not None:
                            goal_id = artifacts.get("goal_id")
                    signal_status = "USED"

        signal_id = _stable("editorial-signal", candidate["candidate_id"])
        signal = source_repository.upsert_editorial_signal(
            {
                "signal_id": signal_id,
                "candidate_id": candidate["candidate_id"],
                "status": signal_status,
                "harness_decision": decision,
                "goal_id": goal_id,
                "routing_id": routing.routing_id,
                "authorization_id": authorization.authorization_id,
                "evidence_refs": [
                    f"telegram-input:{input_record['id']}",
                    f"memory-event:{input_record.get('memory_event_id')}",
                    f"source-candidate:{candidate['candidate_id']}",
                    *([f"research-dossier:{dossier_id}"] if dossier_id else []),
                    *[f"claim:{item['claim_id']}" for item in claims],
                    *(
                        [f"research-item:{research_item_id}"]
                        if research_item_id is not None else []
                    ),
                    *(
                        [f"goal:{goal_id}"]
                        if goal_id is not None else []
                    ),
                ],
                "payload": {
                    "authority": "deepseek_harness",
                    "decision": decision,
                    "reason": (
                        "No claim met the evidence hierarchy required for editorial use."
                        if decision == "REJECT_LOW_EVIDENCE"
                        else (
                            "Verified source intelligence entered the official editorial "
                            "pipeline; production remains a separate authorized stage."
                            if signal_status == "USED"
                            else "Verified source intelligence is preserved for future editorial use."
                        )
                    ),
                    "telegram_input_id": input_record["id"],
                    "memory_event_id": input_record.get("memory_event_id"),
                    "source_url": candidate["source_url"],
                    "verified_claim_ids": [item["claim_id"] for item in verified],
                    "research_dossier_id": dossier_id,
                    "research_item_id": research_item_id,
                    "knowledge_id": knowledge_id,
                    "pipeline_result": pipeline_result,
                    "goal_id": goal_id,
                    "production_dispatched": False,
                },
            }
        )
    finally:
        consume_harness_authorization(authorization)
    return signal


def _source_hierarchy_enforced(claims: list[dict[str, Any]]) -> bool:
    for item in claims:
        payload = dict(item.get("payload") or {})
        hierarchy_evidence = dict(payload.get("hierarchy_evidence") or {})
        verification = str(item.get("verification_status") or "")
        hierarchy = str(item.get("source_hierarchy") or "")
        if verification == "VERIFIED":
            if hierarchy == "OFFICIAL_PRIMARY":
                if hierarchy_evidence.get("official_support") is not True:
                    return False
            elif hierarchy == "MULTIPLE_INDEPENDENT_REPORTS":
                if int(hierarchy_evidence.get("independent_secondary_count") or 0) < 2:
                    return False
            else:
                return False
        elif item.get("semantic_memory_id") is not None:
            return False
    return True


def _human_input_lineage_preserved(
    *,
    candidate: dict[str, Any],
    input_record: dict[str, Any],
    claims: list[dict[str, Any]],
    signal: dict[str, Any],
    dossier: ResearchDossier | None,
) -> bool:
    input_id = int(input_record["id"])
    memory_event_id = input_record.get("memory_event_id")
    if int(candidate.get("telegram_input_id") or 0) != input_id:
        return False
    if dossier is not None:
        provenance = dict(dossier.provenance or {})
        if provenance.get("telegram_input_id") != input_id:
            return False
        if provenance.get("memory_event_id") != memory_event_id:
            return False
    for item in claims:
        lineage = dict((item.get("payload") or {}).get("fact_check_lineage") or {})
        if lineage.get("telegram_input_id") != input_id:
            return False
        if lineage.get("memory_event_id") != memory_event_id:
            return False
        if lineage.get("source_candidate_id") != candidate.get("candidate_id"):
            return False
    signal_payload = dict(signal.get("payload") or {})
    if signal_payload.get("telegram_input_id") != input_id:
        return False
    if signal_payload.get("memory_event_id") != memory_event_id:
        return False

    authorization_id = str(signal.get("authorization_id") or "").strip()
    authorization = (
        get_harness_authorization(authorization_id)
        if authorization_id
        else None
    )
    if authorization is None:
        return False
    auth_lineage = dict(authorization.get("lineage") or {})
    if auth_lineage.get("telegram_input_id") != input_id:
        return False
    if auth_lineage.get("memory_event_id") != memory_event_id:
        return False
    if auth_lineage.get("source_candidate_id") != candidate.get("candidate_id"):
        return False
    expected_dossier = dossier.mission_id if dossier is not None else None
    if auth_lineage.get("research_dossier_id") != expected_dossier:
        return False

    refs = set(signal.get("evidence_refs") or ())
    return (
        f"telegram-input:{input_id}" in refs
        and f"source-candidate:{candidate['candidate_id']}" in refs
    )


def quarantine_premature_source_memory(
    input_record: dict[str, Any],
) -> dict[str, Any]:
    """Deactivate legacy URL memory that was promoted before source verification."""
    if str(input_record.get("classification") or "").lower() != "news":
        return {"quarantined": False}
    claim_id = input_record.get("claim_id")
    memory_id = input_record.get("memory_id")
    changed = False
    if isinstance(claim_id, int) and claim_id > 0:
        changed = update_memory_claim_status(claim_id, "uncertain") or changed
    if isinstance(memory_id, int) and memory_id > 0:
        memory = find_memory_by_source(source_type="memory_claim", source_id=str(claim_id)) if claim_id else []
        target_ids = {memory_id, *[int(item["id"]) for item in memory]}
        for target_id in target_ids:
            changed = update_memory_status(
                target_id,
                "quarantined_unverified_source",
            ) or changed
    if changed:
        update_telegram_source_state(
            int(input_record["id"]),
            source_state="SOURCE_CANDIDATE",
            source_url=str(input_record.get("source_url") or "") or None,
            learning_status="captured",
        )
    return {
        "quarantined": changed,
        "legacy_claim_id": claim_id,
        "legacy_memory_id": memory_id,
    }


def process_telegram_source_intelligence(
    *,
    input_record: dict[str, Any],
    fresh_evidence: Any,
) -> dict[str, Any]:
    source_url = str(input_record.get("source_url") or "").strip()
    if str(input_record.get("classification") or "").lower() != "news" or not source_url:
        return {
            "SOURCE_INTELLIGENCE": "NOT_APPLICABLE",
            "INPUT_CAPTURED": "PASS",
        }

    if (
        getattr(fresh_evidence, "status", None) != "PASS"
        or not str(getattr(fresh_evidence, "execution_id", "") or "").strip()
        or not str(getattr(fresh_evidence, "execution_ref", "") or "").strip()
    ):
        raise ValueError(
            "Telegram source intelligence requires observed fresh research evidence"
        )

    quarantine = quarantine_premature_source_memory(input_record)
    candidate = source_repository.get_source_candidate_by_input(int(input_record["id"]))
    if candidate is None:
        candidate_id = _stable(
            "source",
            f"{input_record.get('telegram_chat_id')}:{input_record.get('telegram_message_id')}:{source_url}",
        )
        candidate = source_repository.upsert_source_candidate(
            candidate_id=candidate_id,
            telegram_input_id=int(input_record["id"]),
            source_url=source_url,
            provenance={
                "source": "telegram",
                "telegram_input_id": input_record["id"],
                "memory_event_id": input_record.get("memory_event_id"),
            },
        )

    packet = dict(getattr(fresh_evidence, "packet", {}) or {})
    submitted = packet.get("submitted_source")
    resolution = (
        str(submitted.get("resolution_status") or "FAIL")
        if isinstance(submitted, dict)
        else "FAIL"
    )
    fetch_refs = [
        f"telegram-input:{input_record['id']}",
        f"memory-event:{input_record.get('memory_event_id')}",
        f"source-candidate:{candidate['candidate_id']}",
        f"fresh-research:{getattr(fresh_evidence, 'execution_id', '')}",
        f"fresh-research-ref:{getattr(fresh_evidence, 'execution_ref', '')}",
    ]
    if resolution != "PASS":
        candidate = source_repository.transition_source_candidate(
            candidate["candidate_id"],
            state="INSUFFICIENT_EVIDENCE",
            source_content_resolution="FAIL",
            evidence_refs=fetch_refs,
            payload_patch={"fresh_packet": packet},
            provenance={"reason": "submitted source content was not directly resolved"},
        )
        update_telegram_source_state(
            int(input_record["id"]),
            source_state="INSUFFICIENT_EVIDENCE",
            source_url=source_url,
            learning_status="captured",
        )
        signal = _editorial_decision(
            candidate=candidate,
            input_record=input_record,
            claims=[],
            dossier_id=None,
        )
        lineage_ok = _human_input_lineage_preserved(
            candidate=candidate,
            input_record=input_record,
            claims=[],
            signal=signal,
            dossier=None,
        )
        return {
            "REAL_TELEGRAM_SOURCE_INPUT": (
                "PASS"
                if input_record.get("memory_event_id") is not None
                and int(input_record.get("id") or 0) > 0
                else "FAIL"
            ),
            "INPUT_CAPTURED": (
                "PASS" if input_record.get("memory_event_id") is not None else "FAIL"
            ),
            "SOURCE_LEARNED": "PASS",
            "CLAIM_VERIFIED": "NO",
            "SOURCE_CONTENT_RESOLVED": "FAIL",
            "FRESH_RESEARCH_TRIGGERED": "PASS",
            "CLAIMS_EXTRACTED": "NO",
            "FACT_CHECK_EXECUTED": "NO",
            "SOURCE_HIERARCHY_ENFORCED": "PASS",
            "UNVERIFIED_CLAIM_NOT_PROMOTED": "PASS",
            "SEMANTIC_MEMORY_PROMOTED": "NO",
            "EDITORIAL_SIGNAL_CREATED": (
                "PASS" if signal.get("signal_id") else "FAIL"
            ),
            "EDITORIAL_SIGNAL_USED": (
                "PASS" if signal.get("status") == "USED" else "NO"
            ),
            "HUMAN_INPUT_LINEAGE_PRESERVED": "PASS" if lineage_ok else "FAIL",
            "PREMATURE_INGRESS_MEMORY_QUARANTINED": (
                "PASS" if quarantine.get("quarantined") else "NOT_REQUIRED"
            ),
            "source_candidate": candidate,
            "claims": [],
            "editorial_signal": signal,
        }

    hierarchy = str(submitted.get("source_hierarchy") or "SECONDARY_REPORT")
    candidate = source_repository.transition_source_candidate(
        candidate["candidate_id"],
        state="FETCHED",
        source_content_resolution="PASS",
        source_hierarchy=hierarchy,
        evidence_refs=fetch_refs,
        payload_patch={"fresh_packet": packet},
        provenance={"submitted_source_sha256": submitted.get("content_sha256")},
    )
    update_telegram_source_state(
        int(input_record["id"]),
        source_state="FETCHED",
        source_url=source_url,
        learning_status="captured",
    )

    dossier = _dossier(
        candidate=candidate,
        input_record=input_record,
        packet=packet,
        execution_id=str(getattr(fresh_evidence, "execution_id", "")),
    )
    dossier_id = dossier.mission_id if dossier is not None else None
    claims_text = list(dossier.claims_extracted) if dossier is not None else _extract_claims(
        str(submitted.get("content_excerpt") or "")
    )
    candidate = source_repository.transition_source_candidate(
        candidate["candidate_id"],
        state="CLAIMS_EXTRACTED",
        research_dossier_id=dossier_id,
        evidence_refs=fetch_refs,
        payload_patch={
            "research_dossier": dossier.to_dict() if dossier is not None else None,
            "claims_extracted": claims_text,
        },
    )
    update_telegram_source_state(
        int(input_record["id"]),
        source_state="CLAIMS_EXTRACTED",
        source_url=source_url,
        learning_status="captured",
    )

    persisted_claims: list[dict[str, Any]] = []
    promoted_memory_ids: list[int] = []
    for index, statement in enumerate(claims_text):
        evidence, hierarchy_evidence = _evidence_for_claim(statement, packet)
        fact_check, fact_lineage = _fact_check(
            candidate=candidate,
            input_record=input_record,
            statement=statement,
            index=index,
            evidence=evidence,
        )
        official_support = bool(hierarchy_evidence["official_support"])
        independent_count = int(hierarchy_evidence["independent_secondary_count"])
        fact_verdict = str(fact_check.get("verdict") or "INSUFFICIENT_EVIDENCE")
        if fact_verdict == "CONTRADICTED":
            verification = "CONTRADICTED"
            claim_hierarchy = "INSUFFICIENT_EVIDENCE"
        elif fact_verdict == "SUPPORTED" and official_support:
            verification = "VERIFIED"
            claim_hierarchy = "OFFICIAL_PRIMARY"
        elif fact_verdict == "SUPPORTED" and independent_count >= 2:
            verification = "VERIFIED"
            claim_hierarchy = "MULTIPLE_INDEPENDENT_REPORTS"
        else:
            verification = "INSUFFICIENT_EVIDENCE"
            claim_hierarchy = (
                "PRIMARY_STATEMENT_REPORTED_BY_SECONDARY"
                if hierarchy == "PRIMARY_STATEMENT_REPORTED_BY_SECONDARY"
                else "INSUFFICIENT_EVIDENCE"
            )
        claim_id = _stable("source-claim", f"{candidate['candidate_id']}:{statement}")
        existing_claim = source_repository.get_source_claim(claim_id)
        evidence_refs = list(dict.fromkeys([
            *fetch_refs,
            *[str(item.get("source_ref")) for item in evidence if item.get("source_ref")],
            f"fact-check-routing:{fact_lineage['routing_id']}",
            f"fact-check-authorization:{fact_lineage['authorization_id']}",
            f"fact-check-execution:{fact_lineage['execution_id']}",
        ]))
        # A fact-check can mark a claim VERIFIED, but semantic memory promotion
        # is forbidden until the SourceCandidate itself has crossed FACT_CHECKED
        # and then VERIFIED. Existing semantic memory is preserved only for an
        # idempotent replay of an already promoted claim.
        memory_id = (
            int(existing_claim["semantic_memory_id"])
            if existing_claim is not None
            and existing_claim.get("semantic_memory_id") is not None
            else None
        )
        claim = source_repository.upsert_source_claim(
            {
                "claim_id": claim_id,
                "candidate_id": candidate["candidate_id"],
                "statement": statement,
                "fact_check_result": fact_verdict,
                "verification_status": verification,
                "source_hierarchy": claim_hierarchy,
                "memory_eligible": bool(memory_id),
                "semantic_memory_id": memory_id,
                "source_refs": list(fact_check.get("source_refs") or ()),
                "evidence_refs": evidence_refs,
                "payload": {
                    "fact_check": fact_check,
                    "fact_check_lineage": fact_lineage,
                    "hierarchy_evidence": hierarchy_evidence,
                },
            }
        )
        persisted_claims.append(claim)

    candidate = source_repository.transition_source_candidate(
        candidate["candidate_id"],
        state="FACT_CHECKED",
        evidence_refs=fetch_refs,
        payload_patch={"claim_ids": [item["claim_id"] for item in persisted_claims]},
    )
    update_telegram_source_state(
        int(input_record["id"]),
        source_state="FACT_CHECKED",
        source_url=source_url,
        learning_status="captured",
    )

    verified_claims = [item for item in persisted_claims if item["verification_status"] == "VERIFIED"]
    contradicted_claims = [item for item in persisted_claims if item["verification_status"] == "CONTRADICTED"]
    if verified_claims:
        candidate = source_repository.transition_source_candidate(
            candidate["candidate_id"],
            state="VERIFIED",
            evidence_refs=fetch_refs,
            payload_patch={
                "verified_claim_ids": [item["claim_id"] for item in verified_claims],
            },
        )
        update_telegram_source_state(
            int(input_record["id"]),
            source_state="VERIFIED",
            source_url=source_url,
            learning_status="captured",
        )

        # MEMORY_ELIGIBLE is a post-verification transition. Only after the
        # candidate is durably VERIFIED may a verified claim become semantic
        # memory. This preserves the causal chain:
        # FACT_CHECKED -> VERIFIED -> semantic promotion -> MEMORY_ELIGIBLE.
        refreshed_claims: list[dict[str, Any]] = []
        for item in persisted_claims:
            if item["verification_status"] != "VERIFIED":
                refreshed_claims.append(item)
                continue
            memory_id = item.get("semantic_memory_id")
            if memory_id is None:
                payload = dict(item.get("payload") or {})
                memory_id = _promote_verified_claim(
                    candidate=candidate,
                    input_record=input_record,
                    statement=str(item["statement"]),
                    fact_check=dict(payload.get("fact_check") or {}),
                    hierarchy=str(item.get("source_hierarchy") or "INSUFFICIENT_EVIDENCE"),
                    evidence_refs=list(item.get("evidence_refs") or ()),
                )
            promoted_memory_ids.append(int(memory_id))
            refreshed_claims.append(
                source_repository.upsert_source_claim(
                    {
                        **item,
                        "memory_eligible": True,
                        "semantic_memory_id": int(memory_id),
                    }
                )
            )
        persisted_claims = refreshed_claims
        terminal_state = "MEMORY_ELIGIBLE" if promoted_memory_ids else "VERIFIED"
        if terminal_state == "MEMORY_ELIGIBLE":
            candidate = source_repository.transition_source_candidate(
                candidate["candidate_id"],
                state=terminal_state,
                semantic_memory_id=promoted_memory_ids[0],
                evidence_refs=fetch_refs,
                payload_patch={"promoted_memory_ids": promoted_memory_ids},
            )
    elif contradicted_claims:
        terminal_state = "CONTRADICTED"
        candidate = source_repository.transition_source_candidate(
            candidate["candidate_id"],
            state=terminal_state,
            evidence_refs=fetch_refs,
        )
    else:
        terminal_state = "INSUFFICIENT_EVIDENCE"
        candidate = source_repository.transition_source_candidate(
            candidate["candidate_id"],
            state=terminal_state,
            evidence_refs=fetch_refs,
        )
    update_telegram_source_state(
        int(input_record["id"]),
        source_state=terminal_state,
        source_url=source_url,
        # learning_status is ingress capture only; semantic promotion is explicit
        # in source_state/source claim identities and must not be conflated.
        learning_status="captured",
    )

    ledger = _claim_ledger(
        dossier=dossier,
        claims=persisted_claims,
    )
    candidate = source_repository.transition_source_candidate(
        candidate["candidate_id"],
        state=terminal_state,
        evidence_refs=fetch_refs,
        payload_patch={"claim_ledger": ledger},
    )
    signal = _editorial_decision(
        candidate=candidate,
        input_record=input_record,
        claims=persisted_claims,
        dossier_id=dossier_id,
    )
    hierarchy_ok = _source_hierarchy_enforced(persisted_claims)
    lineage_ok = _human_input_lineage_preserved(
        candidate=candidate,
        input_record=input_record,
        claims=persisted_claims,
        signal=signal,
        dossier=dossier,
    )
    return {
        "REAL_TELEGRAM_SOURCE_INPUT": (
            "PASS"
            if input_record.get("memory_event_id") is not None
            and int(input_record.get("id") or 0) > 0
            else "FAIL"
        ),
        "INPUT_CAPTURED": (
            "PASS" if input_record.get("memory_event_id") is not None else "FAIL"
        ),
        "SOURCE_LEARNED": (
            "PASS"
            if candidate.get("source_state") in {
                "VERIFIED",
                "CONTRADICTED",
                "INSUFFICIENT_EVIDENCE",
                "MEMORY_ELIGIBLE",
            }
            else "PENDING"
        ),
        "CLAIM_VERIFIED": "PASS" if verified_claims else "NO",
        "SOURCE_CONTENT_RESOLVED": "PASS",
        "FRESH_RESEARCH_TRIGGERED": "PASS",
        "CLAIMS_EXTRACTED": "PASS" if claims_text else "NO",
        "FACT_CHECK_EXECUTED": "PASS" if persisted_claims else "NO",
        "SOURCE_HIERARCHY_ENFORCED": "PASS" if hierarchy_ok else "FAIL",
        "UNVERIFIED_CLAIM_NOT_PROMOTED": (
            "PASS"
            if all(
                item["semantic_memory_id"] is None
                for item in persisted_claims
                if item["verification_status"] != "VERIFIED"
            )
            else "FAIL"
        ),
        "SEMANTIC_MEMORY_PROMOTED": "PASS" if promoted_memory_ids else "NO",
        "EDITORIAL_SIGNAL_CREATED": (
            "PASS" if signal.get("signal_id") else "FAIL"
        ),
        "EDITORIAL_SIGNAL_USED": (
            "PASS" if signal.get("status") == "USED" else "NO"
        ),
        "HUMAN_INPUT_LINEAGE_PRESERVED": "PASS" if lineage_ok else "FAIL",
        "PREMATURE_INGRESS_MEMORY_QUARANTINED": (
            "PASS" if quarantine.get("quarantined") else "NOT_REQUIRED"
        ),
        "source_candidate": candidate,
        "research_dossier": dossier.to_dict() if dossier is not None else None,
        "claim_ledger": ledger,
        "claims": persisted_claims,
        "editorial_signal": signal,
        "promoted_memory_ids": promoted_memory_ids,
    }
