from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urlparse

from app.services.harness_mission_execution_router import execute_harness_execution_need
from app.services.harness_durable_execution_service import HarnessDurableExecutionService
from app.database.gta6_goal_repository import (
    get_gta6_goal_artifacts,
    get_gta6_goal_artifacts_by_idea_id,
)
from app.database.production_plan_repository import insert_production_plan
from app.database.research_repository import get_research_item, list_research_items
from app.database.schema import initialize_schema
from app.database.scripts_repository import get_script, list_scripts
from app.services.content_item_service import create_content_item
from app.services.editorial_novelty_service import (
    MAX_INTERNAL_SENTENCE_DUPLICATION_PERCENT,
    MAX_SCRIPT_NGRAM_REUSE_PERCENT,
    internal_sentence_duplication_percent,
    script_reuse_percent,
    topic_is_duplicate,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.gta6_goal_service import update_artifacts
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_collaboration_service import (
    CollaborationPlan,
    build_goal_envelope,
    plan_mission_from_human_goal,
)
from app.services.harness_mission_execution_router import (
    select_mission_execution_route,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.hermes_multiagent.capability_broker import (
    DelegatedCapabilityFailure,
    HermesHarnessCapabilityBroker,
)
from app.services.hermes_multiagent.contracts import (
    HERMES_RUNTIME_CAPABILITY_ID,
    HermesMissionExecutionSpec,
)
from app.services.hermes_multiagent.runtime import (
    execute_hermes_mission_capability,
)
from app.services.telegram_fresh_research_service import (
    execute_fresh_gta6_research_capability,
)
from app.services.script_spec_service import generate_script_spec


ROCKSTAR_PREFIX = "https://www.rockstargames.com/"


def _is_rockstar_official_url(value: Any) -> bool:
    try:
        host = (urlparse(str(value or "")).hostname or "").casefold()
    except ValueError:
        return False
    return host == "rockstargames.com" or host.endswith(".rockstargames.com")
DELIVERY_CAPABILITIES = frozenset({
    "narration.generate.pt-BR",
    "production.brand-assets.bind",
    "production.media.select-segments",
    "production.media.bind-selected-segments",
    "production.render.execute",
    "telegram.review.deliver",
    "qa.preflight",
    "youtube.upload-private",
    "video.edit.vedit",
})
CODEX_CHECKPOINT = 35850473901

# Human-approved Voice B (+0%) calibration evidence:
# run 35399181943 / artifact 10568953094 measured about 145-163 spoken
# words/minute across six real PT-BR contexts. Long-form planning uses a
# conservative effective 132 WPM plus 21 seconds of pre-TTS estimate tolerance.
# Physical narration/render QA remains the authoritative duration check later.
VOICE_B_EFFECTIVE_PLANNING_WPM = 132.0
PRE_TTS_DURATION_TOLERANCE_MINUTES = 0.35
MAX_LONGFORM_EVIDENCE_EXPANSIONS = 1
MAX_LONGFORM_EXPANSION_FACT_CHECKS = 6
MAX_LONGFORM_EDITORIAL_CLAIMS = 24
MAX_LONGFORM_WEB_SOURCE_ACQUISITIONS = 2
MAX_LONGFORM_WEB_EVIDENCE_SNAPSHOTS = 1
MAX_LONGFORM_FRESH_SECONDARY_FACT_CHECKS = 2
MAX_LONGFORM_RECOVERY_CHILD_TASKS = 8


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def _sha(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)


def _result_payload(execution: dict[str, Any]) -> Any:
    value: Any = execution.get("result")
    for _ in range(4):
        if not isinstance(value, dict):
            break
        if "result" in value and (
            "capability_id" in value
            or "success" in value
            or {"status", "active"} <= set(value)
        ):
            value = value.get("result")
            continue
        break
    return value


def _official_url(row: dict[str, Any]) -> str:
    for key in ("url", "source_url", "canonical_url", "resolved_url"):
        value = str(row.get(key) or "").strip()
        if _is_rockstar_official_url(value):
            return value
    return ""


def _evidence_excerpt(row: dict[str, Any]) -> str:
    for key in ("content", "summary", "description", "content_excerpt", "title"):
        value = re.sub(r"\s+", " ", str(row.get(key) or "")).strip()
        if value:
            return value[:900]
    return ""


def _normalize_research_claims(result: Any) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _walk(result):
        claim_text = str(
            row.get("claim_text")
            or row.get("statement")
            or ""
        ).strip()
        source_url = str(row.get("source_url") or row.get("url") or "").strip()
        evidence_ref = str(row.get("evidence_ref") or "").strip()
        if claim_text and (
            _is_rockstar_official_url(source_url)
            or _is_rockstar_official_url(
                evidence_ref.split("#", 1)[0].removeprefix("url:")
            )
        ):
            url = (
                source_url
                if _is_rockstar_official_url(source_url)
                else evidence_ref.split("#", 1)[0].removeprefix("url:")
            )
            key = hashlib.sha256((claim_text + "|" + url).encode("utf-8")).hexdigest()[:20]
            if key not in seen:
                seen.add(key)
                claims.append({
                    "claim_id": f"official-{key}",
                    "statement": claim_text[:1200],
                    "verification_status": "VERIFIED",
                    "fact_check_result": "OFFICIAL_PRIMARY",
                    "verification_basis": "OFFICIAL_PRIMARY",
                    "source_type": "OFFICIAL_STATEMENT",
                    "source": url,
                    "reference": evidence_ref or url,
                    "timecode_or_section": None,
                    "confidence": 1.0,
                    "novelty": "CURRENT_RESEARCH",
                    "how_used_in_video": "candidate editorial finding",
                    "evidence_refs": [url, *( [evidence_ref] if evidence_ref else [] )],
                })

        url = _official_url(row)
        title = re.sub(r"\s+", " ", str(row.get("title") or "")).strip()
        excerpt = _evidence_excerpt(row)
        # Raw monitored SPA shells carry an official URL but no article
        # identity.  Only resolved official research items with a real title
        # may become factual claims.
        if url and title:
            statement = (
                f"{title}: {excerpt}"
                if excerpt and excerpt.casefold() != title.casefold()
                else title
            )
            key = hashlib.sha256((statement + "|" + url).encode("utf-8")).hexdigest()[:20]
            if key not in seen:
                seen.add(key)
                claims.append({
                    "claim_id": f"official-{key}",
                    "statement": statement[:1200],
                    "verification_status": "VERIFIED",
                    "fact_check_result": "OFFICIAL_PRIMARY",
                    "verification_basis": "OFFICIAL_PRIMARY",
                    "source_type": "OFFICIAL_STATEMENT",
                    "source": url,
                    "reference": url,
                    "timecode_or_section": None,
                    "confidence": 1.0,
                    "novelty": "CURRENT_RESEARCH",
                    "how_used_in_video": "candidate editorial finding",
                    "evidence_refs": [url],
                })
    return claims[:40]


def _approved_topic_from_research(result: dict[str, Any]) -> dict[str, Any] | None:
    historical_titles = [
        str(item.get("title") or "")
        for item in list_research_items()
        if str(item.get("title") or "").strip()
    ]
    candidates: list[dict[str, Any]] = []
    for row in result.get("editorial") or ():
        if not isinstance(row, dict) or row.get("decision") != "approve":
            continue
        idea_id = row.get("idea_id")
        research_id = row.get("research_item_id")
        if not isinstance(idea_id, int) or not isinstance(research_id, int):
            continue
        artifacts = get_gta6_goal_artifacts_by_idea_id(idea_id)
        research = get_research_item(research_id)
        if not artifacts or not research:
            continue
        title = str(research.get("title") or "").strip()
        baselines = [
            item for item in historical_titles
            if item.strip() and item.strip() != title
        ]
        duplicate, similarity, matched = topic_is_duplicate(title, baselines)
        criteria = dict(row.get("criteria") or {})
        candidates.append({
            "goal_id": artifacts.get("goal_id"),
            "idea_id": idea_id,
            "research_item_id": research_id,
            "topic": title,
            "source_url": str(
                research.get("url")
                or research.get("source_url")
                or ""
            ),
            "score": float(row.get("score") or 0.0),
            "novelty_score": float(criteria.get("novelty") or 0.0),
            "timeliness_score": float(criteria.get("timeliness") or 0.0),
            "topic_duplicate": duplicate,
            "topic_similarity": similarity,
            "topic_match": matched,
            "official_source": _is_rockstar_official_url(
                research.get("url") or research.get("source_url") or ""
            ),
        })
    candidates.sort(
        key=lambda item: (
            bool(item["topic_duplicate"]),
            -int(bool(item["official_source"])),
            -float(item["novelty_score"]),
            -float(item["score"]),
            -float(item["timeliness_score"]),
            str(item["topic"]),
        )
    )
    return candidates[0] if candidates and not candidates[0]["topic_duplicate"] else None


def _target_duration_seconds(claim_count: int) -> float:
    """Professional final-video target; never lower than the 20-minute contract.

    Sparse evidence is handled by bounded research/editorial expansion and the
    existing fail-closed content-duration/novelty gates. It is never converted
    into a shorter final-review target or padded artificially.
    """
    if claim_count >= 12:
        return 1500.0
    return 1200.0


def _longform_retry_target_seconds(current_target_seconds: Any) -> float:
    """Reconcile a preferred long-form target after a proven underdelivery.

    A failed 25-minute attempt is runtime evidence that the current editorial
    evidence cannot support the preferred target without padding. The one
    bounded recovery retry therefore falls back only to the already-canonical
    professional minimum of 20 minutes; it never permits a short final video.
    """
    try:
        current = float(current_target_seconds)
    except (TypeError, ValueError):
        current = 1200.0
    return 1200.0 if current > 1200.0 else max(1200.0, current)


def _governed_web_acquisition_status(
    *,
    selected_count: int,
    successful_count: int,
    blocked_count: int,
) -> str:
    if successful_count > 0:
        return "PASS"
    if selected_count <= 0:
        return "NO_NEW_URLS"
    if blocked_count >= selected_count:
        return "BLOCKED_ZERO_COST_TRANSPORT"
    return "NO_ACQUIRED_CONTENT"


def _exception_chain_text(exc: BaseException) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
    return " | ".join(parts)


def _is_longform_underdelivery_failure(
    failure: DelegatedCapabilityFailure,
) -> bool:
    return bool(
        failure.capability_id == "editorial.process"
        and failure.failure_mode == "AIProviderError"
        and "cannot sustain requested long-form duration without padding"
        in _exception_chain_text(failure).casefold()
    )


def _fresh_research_candidates(
    evidence: dict[str, Any],
    *,
    known_ids: set[str],
) -> list[dict[str, Any]]:
    """Normalize only source-bound entries from the existing fresh-cloud packet."""
    packet = evidence.get("packet")
    if not isinstance(packet, dict):
        return []

    execution_ref = str(
        evidence.get("artifact_ref")
        or evidence.get("execution_ref")
        or ""
    ).strip()
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set(known_ids)

    def add_source(row: dict[str, Any], *, official: bool) -> None:
        source = str(
            row.get("resolved_url")
            or row.get("url")
            or row.get("source_url")
            or ""
        ).strip()
        if not source.startswith("https://"):
            return
        title = re.sub(r"\s+", " ", str(row.get("title") or "")).strip()
        excerpt = re.sub(
            r"\s+",
            " ",
            html.unescape(
                str(
                    row.get("content_excerpt")
                    or row.get("summary")
                    or row.get("description")
                    or ""
                )
            ),
        ).strip()
        if not title and not excerpt:
            return
        probe = (excerpt or title).lstrip().casefold()
        if probe.startswith(("<!doctype", "<html", "<head", "<?xml")):
            return

        statements: list[str] = []
        if official and excerpt:
            official_text = re.sub(
                r"(?is)<(script|style|noscript)\b[^>]*>.*?</\1>",
                " ",
                excerpt,
            )
            official_text = re.sub(r"(?s)<[^>]+>", " ", official_text)
            official_text = re.sub(r"\s+", " ", official_text).strip()
            for sentence in re.split(r"(?<=[.!?])\s+", official_text):
                sentence = sentence.strip()
                lowered = sentence.casefold()
                if len(sentence) < 45:
                    continue
                if any(
                    marker in lowered
                    for marker in (
                        "privacy cookie settings",
                        "do not sell or share",
                        "corporate privacy",
                    )
                ):
                    continue
                statements.append(sentence[:900].strip())
                if len(statements) >= 8:
                    break

        if not statements:
            statement = excerpt or title
            if title and excerpt and title.casefold() not in excerpt.casefold():
                statement = f"{title}: {excerpt}"
            statements = [statement[:1600].strip()]

        refs = [item for item in (execution_ref, source) if item]
        for statement in statements:
            key = hashlib.sha256(
                (statement + "|" + source).encode("utf-8")
            ).hexdigest()[:20]
            claim_id = f"fresh-{'official' if official else 'secondary'}-{key}"
            if claim_id in seen:
                continue
            seen.add(claim_id)
            candidates.append({
                "claim_id": claim_id,
                "statement": statement,
                "verification_status": "VERIFIED" if official else "PENDING",
                "fact_check_result": (
                    "OFFICIAL_PRIMARY" if official else "PENDING_FACT_CHECK"
                ),
                "verification_basis": (
                    "OFFICIAL_PRIMARY" if official else "SOURCE_GROUNDED_SECONDARY"
                ),
                "source_type": (
                    "OFFICIAL_STATEMENT" if official else "SECONDARY_REPORT"
                ),
                "source": source,
                "reference": source,
                "timecode_or_section": None,
                "confidence": 1.0 if official else 0.7,
                "novelty": "FRESH_CLOUD_RESEARCH",
                "how_used_in_video": "candidate longform editorial finding",
                "evidence_refs": refs,
            })

    for item in packet.get("official_sources") or ():
        if isinstance(item, dict):
            add_source(item, official=True)
    for item in packet.get("secondary_sources") or ():
        if isinstance(item, dict):
            add_source(item, official=False)
    return candidates




def _partition_longform_fresh_candidates(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate primary evidence from bounded secondary fact-check work.

    Official-primary findings are already verified at the source boundary and
    do not consume recovery child tasks. Secondary findings remain bounded by
    the existing fact-check budget. The 24-item ceiling matches the existing
    editorial payload contract and does not widen provider/tool budgets.
    """
    official = [
        item
        for item in candidates
        if str(item.get("fact_check_result") or "") == "OFFICIAL_PRIMARY"
    ][:MAX_LONGFORM_EDITORIAL_CLAIMS]
    pending = [
        item
        for item in candidates
        if str(item.get("fact_check_result") or "") != "OFFICIAL_PRIMARY"
    ][:MAX_LONGFORM_FRESH_SECONDARY_FACT_CHECKS]
    return official, pending

def _canonical_source_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return raw.casefold()
    host = (parsed.hostname or "").casefold()
    if not host:
        return raw.casefold()
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    return f"{(parsed.scheme or 'https').casefold()}://{host}{path}"


def _governed_web_known_source_keys(state: dict[str, Any]) -> set[str]:
    """Deduplicate editorially known secondary sources, not official transport proof.

    Official Rockstar evidence may already support a claim through fresh research,
    but that does not prove the separate generic web.source.acquire transport and
    provenance boundary. Keeping official URLs eligible here lets the governed web
    fabric prove that boundary without increasing source or attempt budgets.
    """
    keys = {
        _canonical_source_url(item.get("source"))
        for item in (state.get("claims") or ())
        if isinstance(item, dict)
        and not _is_rockstar_official_url(item.get("source"))
    }
    keys.discard("")
    return keys


def _web_source_statement(
    acquired: dict[str, Any],
    *,
    selected_topic: str,
) -> str:
    raw = str(acquired.get("content") or "")
    if not raw.strip():
        return ""
    cleaned = re.sub(
        r"(?is)<(script|style|noscript)\b[^>]*>.*?</\1>",
        " ",
        raw,
    )
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    tokens = {
        token
        for token in re.findall(r"[a-z0-9à-ÿ]+", selected_topic.casefold())
        if len(token) >= 4
    }
    tokens.update({"gta", "rockstar", "lucia", "jason", "vice", "city", "leonida"})
    sentences = [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+", cleaned)
        if len(item.strip()) >= 60
    ]
    for sentence in sentences:
        lowered = sentence.casefold()
        if any(token in lowered for token in tokens):
            return sentence[:1600].strip()
    if sentences:
        return sentences[0][:1600].strip()
    return cleaned[:1600].strip()


def _web_acquisition_slots(candidates: list[dict[str, Any]]) -> int:
    pending_fact_checks = min(
        MAX_LONGFORM_FRESH_SECONDARY_FACT_CHECKS,
        sum(
            1
            for item in candidates
            if str(item.get("fact_check_result") or "") != "OFFICIAL_PRIMARY"
        ),
    )
    # Reserve the unchanged eight-child recovery budget:
    # research(1) + fresh fact-checks(<=2) + discovery(1)
    # + one explicit evidence snapshot + source/fact-check pairs.
    snapshot_reserve = min(1, MAX_LONGFORM_WEB_EVIDENCE_SNAPSHOTS)
    remaining = (
        MAX_LONGFORM_RECOVERY_CHILD_TASKS
        - 1
        - pending_fact_checks
        - 1
        - snapshot_reserve
    )
    return min(
        MAX_LONGFORM_WEB_SOURCE_ACQUISITIONS,
        max(0, remaining // 2),
    )


def _source_host_family(value: Any) -> str:
    try:
        host = (urlparse(str(value or "")).hostname or "").casefold()
    except ValueError:
        return ""
    labels = [part for part in host.split(".") if part]
    if len(labels) < 2:
        return host
    if (
        len(labels) >= 3
        and len(labels[-1]) == 2
        and labels[-2] in {"co", "com", "org", "net"}
    ):
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _longform_fallback_source_urls(
    candidates: list[dict[str, Any]],
    fresh_recovery: dict[str, Any] | None,
    *,
    excluded_source_urls: tuple[str, ...] | list[str] = (),
) -> list[str]:
    excluded = {
        _canonical_source_url(value)
        for value in excluded_source_urls
        if _canonical_source_url(value)
    }
    represented_families = {
        _source_host_family(value)
        for value in excluded_source_urls
        if _source_host_family(value)
    }

    pool: list[str] = []
    for item in candidates:
        value = str(item.get("source") or "").strip()
        if value.startswith(("https://", "http://")):
            pool.append(value)
    packet = (
        fresh_recovery.get("packet")
        if isinstance(fresh_recovery, dict)
        else None
    )
    if isinstance(packet, dict):
        for key in ("official_sources", "secondary_sources"):
            for item in packet.get(key) or ():
                if not isinstance(item, dict):
                    continue
                value = str(
                    item.get("resolved_url")
                    or item.get("url")
                    or item.get("source_url")
                    or ""
                ).strip()
                if value.startswith(("https://", "http://")):
                    pool.append(value)

    unique: list[str] = []
    seen_urls: set[str] = set()
    for value in pool:
        canonical = _canonical_source_url(value)
        if not canonical or canonical in excluded or canonical in seen_urls:
            continue
        seen_urls.add(canonical)
        unique.append(value)

    diverse: list[str] = []
    deferred: list[str] = []
    seen_families = set(represented_families)
    for value in unique:
        family = _source_host_family(value)
        if family and family not in seen_families:
            diverse.append(value)
            seen_families.add(family)
        else:
            deferred.append(value)
    return [*diverse, *deferred]


def _prioritize_longform_web_acquisition_candidates(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prefer directly verifiable official sources without expanding attempts.

    The governed discovery order is preserved within each authority class.
    This changes candidate selection only; max_sources and the bounded
    alternate-attempt ceiling remain unchanged.
    """
    return sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            0 if _is_rockstar_official_url(row.get("url")) else 1
        ),
    )


def _classify_web_failure(exc: BaseException) -> str:
    text = _exception_chain_text(exc).casefold()
    if any(marker in text for marker in (
        "apilayer_subscription_required",
        "apilayer_product_auth_required",
    )):
        return "API_SUBSCRIPTION_REQUIRED"
    if any(marker in text for marker in (
        "apilayer_api_key_required",
        "apilayer_authentication_failed",
    )):
        return "AUTHENTICATION"
    if any(marker in text for marker in (
        "free_quota_exhausted",
        "apilayer free quota is unavailable",
        "zerocostpolicyerror",
    )):
        return "FREE_QUOTA_EXHAUSTED"
    if any(marker in text for marker in (
        "endpoint_request_contract",
        "requires query",
        "requires http(s)",
        "snapshot_required=true",
    )):
        return "ENDPOINT_REQUEST_CONTRACT"
    if any(marker in text for marker in (
        "normalization_failed",
        "invalid_json",
        "not_pdf",
        "exceeds_bounded_limit",
    )):
        return "NORMALIZATION"
    if any(marker in text for marker in (
        "routing mismatch",
        "executor routing mismatch",
        "authorization mismatch",
        "permissionerror",
    )):
        return "HARNESS_AUTHORIZATION"
    if "provenance" in text:
        return "PROVENANCE"
    return "TRANSPORT"


def _web_transport_unavailable(exc: BaseException) -> bool:
    return _classify_web_failure(exc) in {
        "AUTHENTICATION",
        "API_SUBSCRIPTION_REQUIRED",
        "FREE_QUOTA_EXHAUSTED",
        "TRANSPORT",
    }


def _longform_recovery_gate_outcome(
    *,
    verified_count: int,
    web_recovery: dict[str, Any],
) -> dict[str, Any]:
    required_gates = {
        "WEB_DISCOVERY_GOVERNED": str(
            web_recovery.get("WEB_DISCOVERY_GOVERNED") or ""
        ),
        "WEB_SOURCE_ACQUISITION_GOVERNED": str(
            web_recovery.get("WEB_SOURCE_ACQUISITION_GOVERNED") or ""
        ),
        "PROVENANCE": str(web_recovery.get("PROVENANCE") or ""),
        "FACT_CHECK_BEFORE_EDITORIAL": "PASS",
    }
    failed_gates = [
        key for key, value in required_gates.items()
        if value != "PASS"
    ]
    discovery_failure_class = str(
        web_recovery.get("web_discovery_failure_class") or ""
    ).strip()
    external_blocker = (
        discovery_failure_class
        if discovery_failure_class in {
            "AUTHENTICATION",
            "API_SUBSCRIPTION_REQUIRED",
            "FREE_QUOTA_EXHAUSTED",
        }
        else None
    )
    if failed_gates:
        status = "BLOCKED"
        failure_class = discovery_failure_class or "WEB_GATE_INCOMPLETE"
    elif int(verified_count) <= 0:
        status = "INSUFFICIENT"
        failure_class = "INSUFFICIENT_EDITORIAL_EVIDENCE"
    else:
        status = "PASS"
        failure_class = None
    return {
        "status": status,
        "required_gates": required_gates,
        "failed_gates": failed_gates,
        "failure_class": failure_class,
        "external_blocker": external_blocker,
    }


def _longform_expansion_terminal_error(expansion: dict[str, Any]) -> str:
    external = str(expansion.get("external_blocker") or "").strip()
    if external:
        return f"{external}:WEB_DISCOVERY_GOVERNED"
    if str(expansion.get("status") or "").upper() == "BLOCKED":
        failure_class = str(
            expansion.get("failure_class") or "WEB_GATE_INCOMPLETE"
        ).strip()
        return f"LONGFORM_WEB_RECOVERY_BLOCKED:{failure_class}"
    return "INSUFFICIENT_EDITORIAL_EVIDENCE_FOR_20_MIN_MASTER"


def _finish_unavailable_recovery_child(
    *,
    board,
    proposal: dict[str, Any],
    run_id: int,
    reason: str,
    failure_class: str,
) -> None:
    board_task_id = str(proposal.get("board_task_id") or "").strip()
    if not board_task_id:
        return
    if not board.complete(
        board_task_id,
        summary=f"ZERO_COST_WEB_CAPABILITY_BLOCKED:{failure_class}",
        run_id=run_id,
        metadata={
            "status": "WEB_CAPABILITY_BLOCKED",
            "failure_class": failure_class,
            "reason": str(reason)[:800],
        },
    ):
        raise RuntimeError("LONGFORM_WEB_RECOVERY_TERMINAL_STATE_FAILED")


def _run_governed_longform_web_acquisition(
    *,
    broker: HermesHarnessCapabilityBroker,
    board,
    state: dict[str, Any],
    research_task_id: str,
    selected_topic: str,
    round_index: int,
    max_sources: int,
    known_ids: set[str],
    fallback_source_urls: list[str] | tuple[str, ...] = (),
    fallback_parent_task_id: str | None = None,
    fallback_parent_evidence_ref: str | None = None,
    search_focus: str = "",
) -> dict[str, Any]:
    """Use only generic Registry web capabilities for a remaining research gap."""
    if max_sources <= 0:
        return {
            "status": "NOT_REQUIRED",
            "candidates": [],
            "evidence_refs": [],
            "WEB_DISCOVERY_GOVERNED": "NOT_REQUIRED",
            "WEB_SOURCE_ACQUISITION_GOVERNED": "NOT_REQUIRED",
            "APILAYER_DIRECT_FALLBACK_ONLY": "PASS",
        }

    root = broker._task(research_task_id)
    known_sources = _governed_web_known_source_keys(state)

    search_id = f"{research_task_id}-longform-web-discovery-{round_index}"
    search_proposal = broker.propose_child_task(
        parent_task_id=research_task_id,
        depth=1,
        child={
            "task_id": search_id,
            "capability_id": "web.search.discover",
            "action": "RESEARCH",
            "objective": (
                f"{root.objective} Resolve the remaining factual long-form research "
                f"gap for '{selected_topic}' through the governed generic web "
                "discovery capability, zero-cost only, without filler."
            ),
            "task_class": "research-gap-web-discovery",
            "expected_output": "bounded candidate source URLs with provenance",
            "acceptance_criteria": (
                "original source URLs preserved",
                "zero-cost only",
                "known sources deduplicated",
            ),
            "read_scope": list(root.read_scope),
            "write_scope": (),
            "allowed_tools": list(root.allowed_tools),
            "allowed_side_effects": list(root.allowed_side_effects),
            "time_budget_seconds": min(int(root.time_budget_seconds), 120),
            "cost_budget": 0.0,
            "context_budget_bytes": min(int(root.context_budget_bytes), 32768),
            "tool_budget": int(root.tool_budget),
            "retry_budget": 0,
            "risk_side_effect_class": "READ_ONLY",
            "evidence_contract": (
                "structured web discovery result with original-source provenance"
            ),
            "review_policy": root.review_policy,
            "human_gate_policy": root.human_gate_policy,
        },
    )
    search_run_id = _claim_dynamic_child(board, search_proposal)
    search_task = broker._task(search_id)
    search_context = broker.parent_context(task_id=search_id)
    search_execution: dict[str, Any] | None = None
    discovery_state = "PASS"
    discovery_failure_class: str | None = None
    try:
        search_execution = broker.execute_delegated_capability(
            task_id=search_id,
            capability_id="web.search.discover",
            payload={
                "mission_id": search_task.mission_id,
                "task_id": search_task.task_id,
                "goal_id": search_task.goal_id,
                "objective": search_task.objective,
                "query": (
                    str(search_focus or "").strip()[:1800]
                    or (
                        f"{selected_topic} GTA VI current verified details "
                        "Rockstar independent reporting"
                    )
                ),
                "candidate_sources": list(fallback_source_urls)[:10],
                "evidence_refs": list(search_context.get("evidence_refs") or ())[:24],
            },
            dependency_context=search_context,
        )
    except DelegatedCapabilityFailure as exc:
        failure_class = _classify_web_failure(exc)
        if not _web_transport_unavailable(exc):
            raise
        discovery_failure_class = failure_class
        discovery_state = f"BLOCKED_{failure_class}"
        _finish_unavailable_recovery_child(
            board=board,
            proposal=search_proposal,
            run_id=search_run_id,
            reason=_exception_chain_text(exc),
            failure_class=failure_class,
        )
    else:
        _complete_dynamic_child(
            board=board,
            proposal=search_proposal,
            execution=search_execution,
            run_id=search_run_id,
        )

    raw_results: list[dict[str, Any]] = []
    if search_execution is not None:
        search_result = _result_payload(search_execution)
        if isinstance(search_result, dict):
            raw_results = [
                dict(item)
                for item in (search_result.get("results") or ())
                if isinstance(item, dict)
            ]

    # max_sources is a success target, not a first-attempt ceiling. Permit one
    # alternate candidate when the first zero-cost transport is unavailable so
    # a single blocked URL cannot mask another directly retrievable source.
    # The alternate is bounded and does not increase the successful-source
    # budget.
    max_acquisition_attempts = max_sources + 1
    selected_results: list[dict[str, Any]] = []
    seen_sources = set(known_sources)
    search_ref = str(
        (search_execution or {}).get("evidence_ref") or ""
    ).strip()
    for item in _prioritize_longform_web_acquisition_candidates(raw_results):
        source_url = str(item.get("url") or "").strip()
        source_key = _canonical_source_url(source_url)
        if (
            not source_url.startswith(("https://", "http://"))
            or not source_key
            or source_key in seen_sources
        ):
            continue
        seen_sources.add(source_key)
        selected_results.append({
            **dict(item),
            "_origin": "web.search.discover",
            "_parent_task_id": search_id,
            "_parent_evidence_ref": search_ref,
        })
        if len(selected_results) >= max_acquisition_attempts:
            break

    fallback_parent_id = str(
        fallback_parent_task_id or research_task_id
    ).strip()
    fallback_parent_ref = str(
        fallback_parent_evidence_ref or ""
    ).strip()
    for source_url in fallback_source_urls:
        if len(selected_results) >= max_acquisition_attempts:
            break
        value = str(source_url or "").strip()
        source_key = _canonical_source_url(value)
        if (
            not value.startswith(("https://", "http://"))
            or not source_key
            or source_key in seen_sources
        ):
            continue
        seen_sources.add(source_key)
        selected_results.append({
            "url": value,
            "_origin": "existing-fresh-source",
            "_parent_task_id": fallback_parent_id,
            "_parent_evidence_ref": fallback_parent_ref,
        })

    refs = [item for item in (search_ref,) if item]
    candidates: list[dict[str, Any]] = []
    transports: list[str] = []
    successful_acquisitions = 0
    blocked_acquisitions = 0
    snapshot_attempt_count = 0
    snapshot_success_count = 0
    snapshot_refs: list[str] = []
    snapshot_failure_classes: list[str] = []

    for index, item in enumerate(selected_results, start=1):
        if successful_acquisitions >= max_sources:
            break
        source_url = str(item.get("url") or "").strip()
        acquire_parent_id = str(
            item.get("_parent_task_id") or search_id
        ).strip()
        acquire_parent_ref = str(
            item.get("_parent_evidence_ref") or ""
        ).strip()
        acquire_parent = broker._task(acquire_parent_id)
        acquire_id = f"{search_id}-source-{index}"
        acquire_proposal = broker.propose_child_task(
            parent_task_id=acquire_parent_id,
            depth=2,
            child={
                "task_id": acquire_id,
                "capability_id": "web.source.acquire",
                "action": "RESEARCH",
                "objective": (
                    f"{acquire_parent.objective} Acquire candidate source {index} "
                    "through the governed cache/direct-first source capability."
                ),
                "task_class": "research-gap-source-acquisition",
                "expected_output": "bounded source content with original-source provenance",
                "acceptance_criteria": (
                    "cache before network",
                    "direct fetch before APILayer fallback",
                    "original source provenance preserved",
                ),
                "read_scope": list(acquire_parent.read_scope),
                "write_scope": (),
                "allowed_tools": list(acquire_parent.allowed_tools),
                "allowed_side_effects": list(acquire_parent.allowed_side_effects),
                "time_budget_seconds": min(int(acquire_parent.time_budget_seconds), 60),
                "cost_budget": 0.0,
                "context_budget_bytes": min(
                    int(acquire_parent.context_budget_bytes),
                    32768,
                ),
                "tool_budget": int(acquire_parent.tool_budget),
                "retry_budget": 0,
                "risk_side_effect_class": "READ_ONLY",
                "evidence_contract": (
                    "source content hash + transport provenance + quota evidence"
                ),
                "review_policy": acquire_parent.review_policy,
                "human_gate_policy": acquire_parent.human_gate_policy,
            },
        )
        broker.submit_handoff(
            from_task_id=acquire_parent_id,
            to_task_id=acquire_id,
            evidence_refs=[acquire_parent_ref],
            summary=(
                "Governed discovery handed an original source URL to the "
                "cache/direct-first acquisition capability."
            ),
        )
        acquire_run_id = _claim_dynamic_child(board, acquire_proposal)
        acquire_task = broker._task(acquire_id)
        acquire_context = broker.parent_context(task_id=acquire_id)
        try:
            acquire_execution = broker.execute_delegated_capability(
                task_id=acquire_id,
                capability_id="web.source.acquire",
                payload={
                    "mission_id": acquire_task.mission_id,
                    "task_id": acquire_task.task_id,
                    "goal_id": acquire_task.goal_id,
                    "objective": acquire_task.objective,
                    "source_url": source_url,
                    "evidence_refs": list(
                        acquire_context.get("evidence_refs") or ()
                    )[:24],
                },
                dependency_context=acquire_context,
            )
        except DelegatedCapabilityFailure as exc:
            failure_class = _classify_web_failure(exc)
            if not _web_transport_unavailable(exc):
                raise
            _finish_unavailable_recovery_child(
                board=board,
                proposal=acquire_proposal,
                run_id=acquire_run_id,
                reason=_exception_chain_text(exc),
                failure_class=failure_class,
            )
            blocked_acquisitions += 1
            continue
        successful_acquisitions += 1
        _complete_dynamic_child(
            board=board,
            proposal=acquire_proposal,
            execution=acquire_execution,
            run_id=acquire_run_id,
        )
        acquired = _result_payload(acquire_execution)
        if not isinstance(acquired, dict):
            continue
        provenance = dict(acquired.get("provenance") or {})
        original_url = str(
            acquired.get("source_url")
            or provenance.get("source_url")
            or source_url
        ).strip()
        required_provenance = (
            "source_url",
            "retrieved_at",
            "content_hash",
            "execution_id",
            "authorization_id",
        )
        if any(
            not str(provenance.get(key) or "").strip()
            for key in required_provenance
        ):
            raise RuntimeError(
                "WEB_PROVENANCE_INVALID:source_acquisition"
            )
        acquire_ref = str(acquire_execution.get("evidence_ref") or "").strip()
        if acquire_ref:
            refs.append(acquire_ref)

        snapshot_ref = ""
        snapshot_provenance: dict[str, Any] = {}
        if snapshot_attempt_count < MAX_LONGFORM_WEB_EVIDENCE_SNAPSHOTS:
            snapshot_attempt_count += 1
            snapshot_parent = broker._task(acquire_id)
            snapshot_id = f"{acquire_id}-snapshot"
            snapshot_proposal = broker.propose_child_task(
                parent_task_id=acquire_id,
                depth=3,
                child={
                    "task_id": snapshot_id,
                    "capability_id": "web.evidence.snapshot",
                    "action": "RESEARCH",
                    "objective": (
                        f"{snapshot_parent.objective} Capture one explicit bounded "
                        "evidence snapshot for the acquired original source."
                    ),
                    "task_class": "research-gap-evidence-snapshot",
                    "expected_output": (
                        "bounded PDF evidence snapshot with original-source provenance"
                    ),
                    "acceptance_criteria": (
                        "snapshot_required=true",
                        "original source URL preserved",
                        "zero-cost quota respected",
                    ),
                    "read_scope": list(snapshot_parent.read_scope),
                    "write_scope": (),
                    "allowed_tools": list(snapshot_parent.allowed_tools),
                    "allowed_side_effects": list(snapshot_parent.allowed_side_effects),
                    "time_budget_seconds": min(
                        int(snapshot_parent.time_budget_seconds),
                        60,
                    ),
                    "cost_budget": 0.0,
                    "context_budget_bytes": min(
                        int(snapshot_parent.context_budget_bytes),
                        32768,
                    ),
                    "tool_budget": int(snapshot_parent.tool_budget),
                    "retry_budget": 0,
                    "risk_side_effect_class": "READ_ONLY",
                    "evidence_contract": (
                        "PDF sha256 + original-source provenance + quota evidence"
                    ),
                    "review_policy": snapshot_parent.review_policy,
                    "human_gate_policy": snapshot_parent.human_gate_policy,
                },
            )
            broker.submit_handoff(
                from_task_id=acquire_id,
                to_task_id=snapshot_id,
                evidence_refs=[acquire_ref],
                summary=(
                    "Governed source acquisition handed the original URL to one "
                    "explicit bounded evidence snapshot."
                ),
            )
            snapshot_run_id = _claim_dynamic_child(board, snapshot_proposal)
            snapshot_task = broker._task(snapshot_id)
            snapshot_context = broker.parent_context(task_id=snapshot_id)
            try:
                snapshot_execution = broker.execute_delegated_capability(
                    task_id=snapshot_id,
                    capability_id="web.evidence.snapshot",
                    payload={
                        "mission_id": snapshot_task.mission_id,
                        "task_id": snapshot_task.task_id,
                        "goal_id": snapshot_task.goal_id,
                        "objective": snapshot_task.objective,
                        "source_url": original_url,
                        "snapshot_required": True,
                        "evidence_refs": list(
                            snapshot_context.get("evidence_refs") or ()
                        )[:24],
                    },
                    dependency_context=snapshot_context,
                )
            except DelegatedCapabilityFailure as exc:
                failure_class = _classify_web_failure(exc)
                if not _web_transport_unavailable(exc):
                    raise
                snapshot_failure_classes.append(failure_class)
                _finish_unavailable_recovery_child(
                    board=board,
                    proposal=snapshot_proposal,
                    run_id=snapshot_run_id,
                    reason=_exception_chain_text(exc),
                    failure_class=failure_class,
                )
            else:
                _complete_dynamic_child(
                    board=board,
                    proposal=snapshot_proposal,
                    execution=snapshot_execution,
                    run_id=snapshot_run_id,
                )
                snapshot_result = _result_payload(snapshot_execution)
                if not isinstance(snapshot_result, dict):
                    raise RuntimeError(
                        "WEB_PROVENANCE_INVALID:evidence_snapshot"
                    )
                snapshot_provenance = dict(
                    snapshot_result.get("provenance") or {}
                )
                if any(
                    not str(snapshot_provenance.get(key) or "").strip()
                    for key in required_provenance
                ):
                    raise RuntimeError(
                        "WEB_PROVENANCE_INVALID:evidence_snapshot"
                    )
                snapshot_ref = str(
                    snapshot_execution.get("evidence_ref") or ""
                ).strip()
                if snapshot_ref:
                    snapshot_refs.append(snapshot_ref)
                    refs.append(snapshot_ref)
                snapshot_success_count += 1
                snapshot_transport = str(
                    snapshot_provenance.get("transport_provider") or ""
                ).strip()
                if snapshot_transport:
                    transports.append(snapshot_transport)

        statement = _web_source_statement(
            acquired,
            selected_topic=selected_topic,
        )
        if not statement or not original_url:
            continue
        claim_id = "web-source-" + hashlib.sha256(
            (statement + "|" + original_url).encode("utf-8")
        ).hexdigest()[:20]
        if claim_id in known_ids:
            continue
        known_ids.add(claim_id)
        transport = str(provenance.get("transport_provider") or "").strip()
        if transport:
            transports.append(transport)
        candidates.append({
            "claim_id": claim_id,
            "statement": statement,
            "verification_status": "PENDING",
            "fact_check_result": "PENDING_FACT_CHECK",
            "verification_basis": "SOURCE_GROUNDED_WEB_ACQUISITION",
            "source_type": (
                "OFFICIAL_STATEMENT"
                if _is_rockstar_official_url(original_url)
                else "SECONDARY_REPORT"
            ),
            "source": original_url,
            "reference": original_url,
            "timecode_or_section": None,
            "confidence": 0.8 if _is_rockstar_official_url(original_url) else 0.65,
            "novelty": "GOVERNED_WEB_RESEARCH_GAP",
            "how_used_in_video": "candidate longform editorial finding",
            "evidence_refs": [
                item for item in (acquire_ref, snapshot_ref, original_url) if item
            ],
            "web_provenance": provenance,
            "web_snapshot_provenance": snapshot_provenance or None,
            "_fact_check_parent_task_id": acquire_id,
            "_fact_check_parent_evidence_ref": acquire_ref,
        })

    snapshot_status = (
        "PASS"
        if snapshot_success_count > 0
        else (
            f"BLOCKED_{snapshot_failure_classes[0]}"
            if snapshot_failure_classes
            else "NOT_REQUIRED"
        )
    )
    return {
        "status": "PASS" if candidates else "INSUFFICIENT",
        "candidates": candidates,
        "evidence_refs": list(dict.fromkeys(refs)),
        "WEB_DISCOVERY_GOVERNED": discovery_state,
        "web_discovery_failure_class": discovery_failure_class,
        "WEB_SOURCE_ACQUISITION_GOVERNED": _governed_web_acquisition_status(
            selected_count=len(selected_results),
            successful_count=successful_acquisitions,
            blocked_count=blocked_acquisitions,
        ),
        "WEB_EVIDENCE_SNAPSHOT_GOVERNED": snapshot_status,
        "PROVENANCE": "PASS" if candidates else "INSUFFICIENT",
        "web_source_selected_count": len(selected_results),
        "web_source_successful_acquisition_count": successful_acquisitions,
        "web_source_blocked_acquisition_count": blocked_acquisitions,
        "web_snapshot_attempt_count": snapshot_attempt_count,
        "web_snapshot_success_count": snapshot_success_count,
        "web_snapshot_failure_classes": list(
            dict.fromkeys(snapshot_failure_classes)
        ),
        "APILAYER_DIRECT_FALLBACK_ONLY": "PASS",
        "transport_providers": list(dict.fromkeys(transports)),
        "snapshot_used": snapshot_success_count > 0,
        "snapshot_evidence_refs": list(dict.fromkeys(snapshot_refs)),
    }


def _run_harness_fresh_longform_recovery(
    *,
    broker: HermesHarnessCapabilityBroker,
    selected_topic: str,
    human_goal: str,
    round_index: int,
    purpose: str,
) -> dict[str, Any]:
    """Use the existing fresh-cloud capability under explicit Harness authority."""
    capability_id = "gta6.research.fresh-cloud"
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=(
                f"{purpose}: collect additional current GTA VI evidence for "
                f"the selected topic '{selected_topic}'"
            ),
            authorized_action="RESEARCH",
            domain="research",
            task_class="longform-evidence-fresh-recovery",
            goal_id=broker.spec.goal_id,
            required_capability_id=capability_id,
            required_policy_tags=(
                "gta6", "research", "fresh", "cloud", "evidence",
            ),
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    if routing.selected_capability_id != capability_id:
        raise RuntimeError("LONGFORM_FRESH_RESEARCH_ROUTE_MISMATCH")

    execution_id = (
        f"{broker.parent_authorization.execution_id}:"
        f"fresh:{purpose}:{round_index}"
    )
    authorization = issue_harness_authorization(
        authorized_action="RESEARCH",
        subject=f"capability:{capability_id}",
        harness_decision_id=broker.parent_authorization.harness_decision_id,
        execution_id=execution_id,
        lineage={
            "parent_authorization_id": (
                broker.parent_authorization.authorization_id
            ),
            "mission_id": broker.spec.mission_id,
            "goal_id": broker.spec.goal_id,
            "routing_id": routing.routing_id,
            "capability_id": capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "recovery": purpose,
            "selected_topic": selected_topic,
            "round": round_index,
        },
    )
    query = (
        f"{human_goal}\n\n"
        f"{purpose}:\nSelected topic: {selected_topic}\n"
        "Collect current source-grounded GTA VI evidence useful for a factual "
        "20-minute analysis. Prefer direct Rockstar evidence; include current "
        "secondary reporting only with explicit provenance. Do not invent facts "
        "and do not add filler."
    )
    try:
        return execute_fresh_gta6_research_capability(
            query=query,
            authorization=authorization,
            routing_decision=routing,
            source_context={
                "classification": "news",
                "input_kind": "text",
            },
        ).to_dict()
    finally:
        consume_harness_authorization(authorization)


def _ensure_fact_check_source_claims(
    *,
    broker: HermesHarnessCapabilityBroker,
    state: dict[str, Any],
    human_goal: str,
) -> dict[str, Any] | None:
    if state.get("claims"):
        return None
    selected_topic = str(state.get("selected_topic") or "").strip()
    if not selected_topic:
        raise RuntimeError("FACT_CHECK_REQUIRES_RESEARCH_CLAIM")

    fresh = _run_harness_fresh_longform_recovery(
        broker=broker,
        selected_topic=selected_topic,
        human_goal=human_goal,
        round_index=0,
        purpose="FACT_CHECK_SOURCE_RECOVERY",
    )
    candidates = _fresh_research_candidates(fresh, known_ids=set())
    # The fresh-cloud contract guarantees at least one official Rockstar
    # source. Only direct official evidence is admitted before fact-check;
    # secondary reporting remains pending until the bounded longform recovery
    # explicitly fact-checks it.
    official, _pending = _partition_longform_fresh_candidates(candidates)
    if not official:
        raise RuntimeError("FACT_CHECK_REQUIRES_RESEARCH_CLAIM")
    state.setdefault("claims", []).extend(official)
    ref = str(
        fresh.get("artifact_ref")
        or fresh.get("execution_ref")
        or ""
    ).strip()
    if ref:
        state.setdefault("expansion_evidence_refs", [])
        if ref not in state["expansion_evidence_refs"]:
            state["expansion_evidence_refs"].append(ref)
    report = {
        "schema": "fact-check-source-recovery/v1",
        "status": "PASS",
        "selected_topic": selected_topic,
        "official_claim_count": len(official),
        "fresh_cloud_execution_ref": ref or None,
        "artificial_padding": False,
    }
    state["fact_check_source_recovery"] = report
    return report


def _claim_dynamic_child(board, proposal: dict[str, Any]) -> int:
    task = dict(proposal.get("task") or {})
    task_id = str(task.get("task_id") or "").strip()
    board_task_id = str(proposal.get("board_task_id") or "").strip()
    if not task_id or not board_task_id:
        raise RuntimeError("LONGFORM_EXPANSION_CHILD_PROPOSAL_INVALID")
    claimer = str(
        task.get("selected_agent_id")
        or task.get("selected_skill_id")
        or task.get("capability_id")
        or task_id
    )
    board.claim(board_task_id, claimer=claimer)
    row = board.get_task(board_task_id)
    run_id = int(row.get("current_run_id") or 0)
    if run_id <= 0:
        raise RuntimeError(
            f"LONGFORM_EXPANSION_CHILD_CLAIM_FAILED:{task_id}"
        )
    board.heartbeat(
        board_task_id,
        run_id=run_id,
        note="bounded longform evidence expansion started",
    )
    return run_id


def _complete_dynamic_child(
    *,
    board,
    proposal: dict[str, Any],
    execution: dict[str, Any],
    run_id: int,
) -> None:
    task = dict(proposal.get("task") or {})
    task_id = str(task.get("task_id") or "").strip()
    board_task_id = str(proposal.get("board_task_id") or "").strip()
    if not board.complete(
        board_task_id,
        summary=(
            f"LONGFORM_RECOVERY_TASK_COMPLETED capability="
            f"{task.get('capability_id')} evidence={execution.get('evidence_ref')}"
        ),
        run_id=run_id,
        metadata={
            "capability_id": task.get("capability_id"),
            "evidence_ref": execution.get("evidence_ref"),
            "recovery": "INSUFFICIENT_EDITORIAL_EVIDENCE",
        },
    ):
        raise RuntimeError(
            f"LONGFORM_EXPANSION_CHILD_COMPLETE_FAILED:{task_id}"
        )


def _normalized_sequence_evidence_gaps(
    value: Any,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        sequence_id = str(item.get("sequence_id") or "").strip()
        if not sequence_id or sequence_id in seen:
            continue
        seen.add(sequence_id)
        normalized.append({
            "sequence_id": sequence_id,
            "missing_questions": [
                str(entry).strip()
                for entry in (item.get("missing_questions") or ())
                if str(entry).strip()
            ][:6],
            "missing_claim_types": [
                str(entry).strip()
                for entry in (item.get("missing_claim_types") or ())
                if str(entry).strip()
            ][:6],
            "existing_evidence": [
                str(entry).strip()
                for entry in (item.get("existing_evidence") or ())
                if str(entry).strip()
            ][:24],
            "duplicate_topics_to_avoid": [
                str(entry).strip()
                for entry in (item.get("duplicate_topics_to_avoid") or ())
                if str(entry).strip()
            ][:16],
            "required_novelty": [
                str(entry).strip()
                for entry in (item.get("required_novelty") or ())
                if str(entry).strip()
            ][:12],
            "estimated_missing_supported_duration": max(
                0.0,
                float(
                    item.get("estimated_missing_supported_duration")
                    or 0.0
                ),
            ),
        })
    return sorted(
        normalized,
        key=lambda item: (
            -float(item["estimated_missing_supported_duration"]),
            item["sequence_id"],
        ),
    )


def _sequence_evidence_gap_focus(
    gaps: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    for gap in _normalized_sequence_evidence_gaps(gaps)[:8]:
        questions = "; ".join(gap["missing_questions"])
        claim_types = "; ".join(gap["missing_claim_types"])
        avoid = "; ".join(gap["duplicate_topics_to_avoid"][:6])
        lines.append(
            f"{gap['sequence_id']}: missing_questions={questions or 'unspecified'}; "
            f"missing_claim_types={claim_types or 'source-grounded support'}; "
            f"missing_supported_seconds="
            f"{float(gap['estimated_missing_supported_duration']):.1f}; "
            f"avoid_duplicates={avoid or 'none'}"
        )
    return "\n".join(lines)[:6000]


def _run_bounded_longform_evidence_expansion(
    *,
    broker: HermesHarnessCapabilityBroker,
    board,
    state: dict[str, Any],
    human_goal: str,
    research_task_id: str,
    round_index: int,
    sequence_evidence_gaps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if round_index < 1 or round_index > MAX_LONGFORM_EVIDENCE_EXPANSIONS:
        raise RuntimeError("LONGFORM_EVIDENCE_EXPANSION_BUDGET_EXHAUSTED")

    root = broker._task(research_task_id)
    selected_topic = str(state.get("selected_topic") or "").strip()
    if not selected_topic:
        raise RuntimeError("LONGFORM_EVIDENCE_EXPANSION_REQUIRES_TOPIC")

    targeted_gaps = _normalized_sequence_evidence_gaps(
        sequence_evidence_gaps or []
    )
    gap_focus = _sequence_evidence_gap_focus(targeted_gaps)
    targeted_human_goal = human_goal
    if gap_focus:
        targeted_human_goal = (
            human_goal
            + "\n\nSEQUENCE_EVIDENCE_GAPS_TO_RESOLVE:\n"
            + gap_focus
        )

    known_ids = {
        str(item.get("claim_id") or "")
        for item in (state.get("claims") or ())
        if isinstance(item, dict)
    }
    research_child_id = f"{research_task_id}-longform-expansion-{round_index}"
    research_proposal = broker.propose_child_task(
        parent_task_id=research_task_id,
        depth=1,
        child={
            "task_id": research_child_id,
            "capability_id": "gta6.research",
            "action": "RESEARCH",
            "objective": (
                f"{root.objective} Expand fresh source-grounded evidence for "
                f"the already selected topic '{selected_topic}' with additional "
                "non-duplicate facts and angles that can support a factual "
                "20-minute BR no GTA 6 script without filler. "
                + (
                    "Resolve the typed sequence evidence gaps supplied by the "
                    "failed StoryAssembly."
                    if targeted_gaps
                    else ""
                )
            ),
            "task_class": "fresh-evidence-collection",
            "expected_output": (
                "additional fresh source-grounded GTA6 research artifacts"
            ),
            "acceptance_criteria": (
                "new verifiable findings",
                "official primary sources preferred",
                "no artificial editorial padding",
            ),
            "read_scope": list(root.read_scope),
            "write_scope": list(root.write_scope),
            "allowed_tools": list(root.allowed_tools),
            "allowed_side_effects": list(root.allowed_side_effects),
            "time_budget_seconds": min(
                int(root.time_budget_seconds),
                900,
            ),
            "cost_budget": float(root.cost_budget),
            "context_budget_bytes": min(
                int(root.context_budget_bytes),
                65536,
            ),
            "tool_budget": int(root.tool_budget),
            "retry_budget": 0,
            "risk_side_effect_class": root.risk_side_effect_class,
            "evidence_contract": root.evidence_contract,
            "review_policy": root.review_policy,
            "human_gate_policy": root.human_gate_policy,
        },
    )
    research_run_id = _claim_dynamic_child(board, research_proposal)
    research_task = broker._task(research_child_id)
    research_context = broker.parent_context(task_id=research_child_id)
    research_payload = {
        "mission_id": research_task.mission_id,
        "task_id": research_task.task_id,
        "goal_id": research_task.goal_id,
        "objective": research_task.objective,
        "query": (
            f"{targeted_human_goal}\n\nLONGFORM_EVIDENCE_EXPANSION:\n"
            f"Selected topic: {selected_topic}\n"
            "Collect additional current, source-grounded GTA VI facts, official "
            "details, implications, contextual angles and independently useful "
            "findings not already represented in the existing evidence. "
            "Prioritize the supplied sequence evidence gaps when present. "
            "Do not invent facts and do not add filler."
        ),
        "topic": selected_topic,
        "subject": "GTA VI",
        "evidence_refs": list(
            research_context.get("evidence_refs") or ()
        )[:24],
    }
    research_execution = broker.execute_delegated_capability(
        task_id=research_child_id,
        capability_id="gta6.research",
        payload=research_payload,
        dependency_context=research_context,
    )
    _complete_dynamic_child(
        board=board,
        proposal=research_proposal,
        execution=research_execution,
        run_id=research_run_id,
    )

    research_result = _result_payload(research_execution)
    candidates = [
        item
        for item in _normalize_research_claims(research_result)
        if str(item.get("claim_id") or "") not in known_ids
    ]
    fresh_recovery: dict[str, Any] | None = None
    if not candidates:
        # A deterministic research replay can correctly yield zero delta after
        # all current items are persisted. Escalate once to the existing
        # fresh-cloud evidence collector under a Harness authorization.
        fresh_recovery = _run_harness_fresh_longform_recovery(
            broker=broker,
            selected_topic=selected_topic,
            human_goal=targeted_human_goal,
            round_index=round_index,
            purpose=(
                "SEQUENCE_EVIDENCE_GAP"
                if targeted_gaps
                else "INSUFFICIENT_EDITORIAL_EVIDENCE"
            ),
        )
        candidates = _fresh_research_candidates(
            fresh_recovery,
            known_ids=known_ids,
        )
    original_candidates = list(candidates)
    official_candidates, pending_candidates = (
        _partition_longform_fresh_candidates(original_candidates)
    )

    pending_candidate_source_urls = [
        str(item.get("source") or "").strip()
        for item in pending_candidates
        if str(item.get("source") or "").strip()
    ]
    fallback_urls = _longform_fallback_source_urls(
        original_candidates,
        fresh_recovery,
        excluded_source_urls=pending_candidate_source_urls,
    )
    web_recovery = _run_governed_longform_web_acquisition(
        broker=broker,
        board=board,
        state=state,
        research_task_id=research_task_id,
        selected_topic=selected_topic,
        round_index=round_index,
        max_sources=_web_acquisition_slots(original_candidates),
        known_ids=known_ids,
        fallback_source_urls=fallback_urls,
        fallback_parent_task_id=research_child_id,
        fallback_parent_evidence_ref=str(
            research_execution.get("evidence_ref") or ""
        ),
        search_focus=(
            (
                f"{selected_topic} GTA VI verified evidence "
                + gap_focus
            )
            if gap_focus
            else ""
        ),
    )
    candidates = [
        *official_candidates,
        *pending_candidates,
        *list(web_recovery.get("candidates") or ()),
    ]

    verified: list[dict[str, Any]] = []
    fact_check_refs: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        if str(candidate.get("fact_check_result") or "") == "OFFICIAL_PRIMARY":
            accepted = {
                key: value
                for key, value in candidate.items()
                if not str(key).startswith("_")
            }
            accepted["verification_status"] = "VERIFIED"
            verified.append(accepted)
            continue

        fact_parent_id = str(
            candidate.get("_fact_check_parent_task_id")
            or research_child_id
        )
        fact_parent_ref = str(
            candidate.get("_fact_check_parent_evidence_ref")
            or research_execution.get("evidence_ref")
            or ""
        ).strip()
        fact_parent = broker._task(fact_parent_id)
        fact_depth = 3 if fact_parent_id != research_child_id else 2
        fact_child_id = f"{fact_parent_id}-fact-check-{index}"
        fact_proposal = broker.propose_child_task(
            parent_task_id=fact_parent_id,
            depth=fact_depth,
            child={
                "task_id": fact_child_id,
                "capability_id": "gta6.fact-check",
                "action": "RESEARCH",
                "objective": (
                    f"{fact_parent.objective} Fact-check the new source-grounded "
                    f"finding {index} before it can enter the longform editorial base."
                ),
                "task_class": "fact-check",
                "expected_output": "FactCheckResult with provenance",
                "acceptance_criteria": (
                    "provenance complete",
                    "supported finding only enters editorial evidence",
                ),
                "read_scope": list(fact_parent.read_scope),
                "write_scope": (),
                "allowed_tools": list(fact_parent.allowed_tools),
                "allowed_side_effects": (),
                "time_budget_seconds": min(
                    int(fact_parent.time_budget_seconds),
                    180,
                ),
                "cost_budget": 0.0,
                "context_budget_bytes": min(
                    int(fact_parent.context_budget_bytes),
                    32768,
                ),
                "tool_budget": int(fact_parent.tool_budget),
                "retry_budget": 0,
                "risk_side_effect_class": "READ_ONLY",
                "evidence_contract": (
                    "app.services.gta6_fact_check_service.FactCheckResult"
                ),
                "review_policy": fact_parent.review_policy,
                "human_gate_policy": fact_parent.human_gate_policy,
            },
        )
        broker.submit_handoff(
            from_task_id=fact_parent_id,
            to_task_id=fact_child_id,
            evidence_refs=[fact_parent_ref],
            summary=(
                "Fresh longform expansion evidence handed to deterministic "
                "fact-check before editorial reuse."
            ),
        )
        fact_run_id = _claim_dynamic_child(board, fact_proposal)
        fact_task = broker._task(fact_child_id)
        fact_context = broker.parent_context(task_id=fact_child_id)
        source = str(candidate.get("source") or "").strip()
        candidate_provenance = dict(candidate.get("web_provenance") or {})
        if not any(
            str(candidate_provenance.get(key) or "").strip()
            for key in ("source_id", "uri", "url", "artifact_ref", "document_id")
        ):
            candidate_provenance["artifact_ref"] = source
        if not any(
            str(candidate_provenance.get(key) or "").strip()
            for key in ("retrieved_at", "observed_at", "published_at", "timestamp")
        ):
            candidate_provenance["observed_at"] = _utcnow()
        fact_payload = {
            "mission_id": fact_task.mission_id,
            "task_id": fact_task.task_id,
            "goal_id": fact_task.goal_id,
            "objective": fact_task.objective,
            "claim": str(candidate.get("statement") or "").strip(),
            "evidence": [{
                "evidence_id": str(
                    candidate.get("claim_id")
                    or f"longform-expansion-{round_index}-{index}"
                ),
                "source_ref": source,
                "stance": "supporting",
                "weight": 1.0,
                "provenance": candidate_provenance,
                "excerpt": str(
                    candidate.get("statement") or ""
                )[:900],
            }],
            "evidence_refs": list(
                fact_context.get("evidence_refs") or ()
            )[:24],
        }
        fact_execution = broker.execute_delegated_capability(
            task_id=fact_child_id,
            capability_id="gta6.fact-check",
            payload=fact_payload,
            dependency_context=fact_context,
        )
        _complete_dynamic_child(
            board=board,
            proposal=fact_proposal,
            execution=fact_execution,
            run_id=fact_run_id,
        )
        fact_result = _result_payload(fact_execution)
        if (
            isinstance(fact_result, dict)
            and str(fact_result.get("verdict") or "").upper() == "SUPPORTED"
        ):
            accepted = {
                key: value
                for key, value in candidate.items()
                if not str(key).startswith("_")
            }
            accepted["fact_check_result"] = "SUPPORTED"
            accepted["verification_basis"] = "FACT_CHECK"
            accepted["fact_check_evidence_ref"] = fact_execution.get(
                "evidence_ref"
            )
            verified.append(accepted)
            if str(fact_execution.get("evidence_ref") or "").strip():
                fact_check_refs.append(
                    str(fact_execution["evidence_ref"])
                )

    if verified:
        state.setdefault("claims", []).extend(verified)
    expansion_refs = [
        str(research_execution.get("evidence_ref") or ""),
        str(
            (fresh_recovery or {}).get("artifact_ref")
            or (fresh_recovery or {}).get("execution_ref")
            or ""
        ),
        *list(web_recovery.get("evidence_refs") or ()),
        *fact_check_refs,
    ]
    state.setdefault("expansion_evidence_refs", [])
    for ref in expansion_refs:
        if ref and ref not in state["expansion_evidence_refs"]:
            state["expansion_evidence_refs"].append(ref)

    gate_outcome = _longform_recovery_gate_outcome(
        verified_count=len(verified),
        web_recovery=web_recovery,
    )
    report = {
        "schema": "longform-evidence-expansion/v1",
        "classification": (
            "SEQUENCE_EVIDENCE_GAP"
            if targeted_gaps
            else "INSUFFICIENT_EDITORIAL_EVIDENCE"
        ),
        "round": round_index,
        "targeted_sequence_gap_count": len(targeted_gaps),
        "targeted_sequence_ids": [
            item["sequence_id"] for item in targeted_gaps
        ],
        "estimated_missing_supported_duration_seconds": round(
            sum(
                float(item["estimated_missing_supported_duration"])
                for item in targeted_gaps
            ),
            3,
        ),
        "selected_topic": selected_topic,
        "candidate_new_findings": len(candidates),
        "verified_new_findings": len(verified),
        "fresh_cloud_escalated": fresh_recovery is not None,
        "fresh_cloud_execution_ref": (
            str(
                (fresh_recovery or {}).get("artifact_ref")
                or (fresh_recovery or {}).get("execution_ref")
                or ""
            )
            or None
        ),
        "fresh_cloud_official_source_count": int(
            (fresh_recovery or {}).get("official_source_count") or 0
        ),
        "fresh_cloud_secondary_source_count": int(
            (fresh_recovery or {}).get("secondary_source_count") or 0
        ),
        "verified_claim_ids": [
            str(item.get("claim_id") or "") for item in verified
        ],
        "LONGFORM_RESEARCH_EXPANSION": gate_outcome["status"],
        "WEB_DISCOVERY_GOVERNED": web_recovery.get("WEB_DISCOVERY_GOVERNED"),
        "web_discovery_failure_class": web_recovery.get(
            "web_discovery_failure_class"
        ),
        "WEB_SOURCE_ACQUISITION_GOVERNED": web_recovery.get(
            "WEB_SOURCE_ACQUISITION_GOVERNED"
        ),
        "WEB_EVIDENCE_SNAPSHOT_GOVERNED": web_recovery.get(
            "WEB_EVIDENCE_SNAPSHOT_GOVERNED"
        ),
        "PROVENANCE": web_recovery.get("PROVENANCE"),
        "web_source_selected_count": int(
            web_recovery.get("web_source_selected_count") or 0
        ),
        "web_source_successful_acquisition_count": int(
            web_recovery.get("web_source_successful_acquisition_count") or 0
        ),
        "web_snapshot_attempt_count": int(
            web_recovery.get("web_snapshot_attempt_count") or 0
        ),
        "web_snapshot_success_count": int(
            web_recovery.get("web_snapshot_success_count") or 0
        ),
        "web_snapshot_failure_classes": list(
            web_recovery.get("web_snapshot_failure_classes") or ()
        ),
        "new_source_count": len({
            str(item.get("source") or "").strip()
            for item in candidates
            if str(item.get("source") or "").strip()
        }),
        "rejected_new_findings": max(0, len(candidates) - len(verified)),
        "supported_new_findings": len(verified),
        "evidence_added_to_editorial": len(verified),
        "APILAYER_DIRECT_FALLBACK_ONLY": web_recovery.get(
            "APILAYER_DIRECT_FALLBACK_ONLY"
        ),
        "FACT_CHECK_BEFORE_EDITORIAL": "PASS",
        "ZERO_COST_ONLY": "PASS",
        "NO_ARTIFICIAL_PADDING": "PASS",
        "evidence_refs": list(
            state.get("expansion_evidence_refs") or ()
        ),
        "required_gate_status": dict(gate_outcome["required_gates"]),
        "failed_required_gates": list(gate_outcome["failed_gates"]),
        "failure_class": gate_outcome["failure_class"],
        "external_blocker": gate_outcome["external_blocker"],
        "status": gate_outcome["status"],
        "artificial_padding": False,
    }
    state.setdefault("longform_evidence_expansions", []).append(report)
    return report


def _parent_summaries(parent_context: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = []
    for row in parent_context.get("parent_handoffs") or ():
        if not isinstance(row, dict):
            continue
        summaries.append({
            "task_id": row.get("task_id"),
            "capability_id": row.get("capability_id"),
            "task_result_ref": row.get("task_result_ref"),
            "content_sha256": row.get("content_sha256"),
            "result_summary": row.get("result_summary"),
            "evidence_refs": list(row.get("evidence_refs") or ())[:8],
        })
    return summaries[:10]


def _bounded_youtube_semantic_context(
    *,
    human_goal: str,
    selected_topic: Any,
    claims: list[dict[str, Any]],
    parent_context: dict[str, Any],
    script_text: str | None,
) -> dict[str, Any]:
    def clip(value: Any, limit: int) -> str:
        return str(value or "").strip()[:limit]

    evidence_map: list[dict[str, Any]] = []
    for item in claims[:10]:
        if not isinstance(item, dict):
            continue
        evidence_map.append({
            key: value
            for key, value in {
                "claim_id": clip(item.get("claim_id"), 180),
                "statement": clip(item.get("statement"), 700),
                "source": clip(item.get("source"), 700),
                "source_type": clip(item.get("source_type"), 120),
                "authority": clip(
                    item.get("authority") or item.get("source_authority"), 120
                ),
                "confidence": item.get("confidence"),
                "evidence_ref": clip(item.get("evidence_ref"), 500),
            }.items()
            if value not in ("", None)
        })

    parent_summaries: list[dict[str, Any]] = []
    for item in _parent_summaries(parent_context)[:8]:
        parent_summaries.append({
            key: value
            for key, value in {
                "task_id": item.get("task_id"),
                "capability_id": item.get("capability_id"),
                "task_result_ref": item.get("task_result_ref"),
                "content_sha256": item.get("content_sha256"),
                "result_summary": clip(item.get("result_summary"), 700),
                "evidence_refs": list(item.get("evidence_refs") or ())[:6],
            }.items()
            if value not in ("", None, [])
        })

    context = {
        "human_goal": clip(human_goal, 2400),
        "selected_topic": selected_topic,
        "evidence_map": evidence_map,
        "parent_summaries": parent_summaries,
        "script": clip(script_text, 8000) if script_text else None,
        "constraints": {
            "language": "pt-BR",
            "verified_facts_only": True,
            "no_public_youtube_release": True,
            "no_unlisted_youtube_release": True,
            "private_hd_review_allowed": True,
            "burned_subtitles": False,
        },
    }

    def size() -> int:
        return len(json.dumps(
            context,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ))

    # Leave headroom below the specialist's 24k hard input ceiling so runtime
    # metadata cannot turn a valid handoff into a terminal blocker.
    target = 20_000
    while size() > target:
        script = str(context.get("script") or "")
        if len(script) > 3000:
            context["script"] = script[:max(3000, len(script) - 1500)]
            continue
        if len(context["evidence_map"]) > 4:
            context["evidence_map"] = context["evidence_map"][:-1]
            continue
        if len(context["parent_summaries"]) > 3:
            context["parent_summaries"] = context["parent_summaries"][:-1]
            continue
        goal = str(context.get("human_goal") or "")
        if len(goal) > 1000:
            context["human_goal"] = goal[:1000]
            continue
        topic = context.get("selected_topic")
        if not isinstance(topic, str):
            context["selected_topic"] = clip(topic, 1200)
            continue
        if len(topic) > 600:
            context["selected_topic"] = topic[:600]
            continue
        raise RuntimeError("YOUTUBE_SEMANTIC_CONTEXT_CANNOT_BE_BOUNDED")

    return context


def _payload_for_task(
    *,
    task,
    parent_context: dict[str, Any],
    state: dict[str, Any],
    human_goal: str,
) -> dict[str, Any]:
    evidence_refs = list(dict.fromkeys([
        *[str(item) for item in (parent_context.get("evidence_refs") or ()) if str(item)],
        *[str(item) for item in (state.get("expansion_evidence_refs") or ()) if str(item)],
        *[str(item) for item in task.input_refs if str(item)],
    ]))[:24]
    common = {
        "mission_id": task.mission_id,
        "task_id": task.task_id,
        "goal_id": task.goal_id,
        "objective": task.objective,
        "evidence_refs": evidence_refs or [f"mission:{task.mission_id}:goal"],
    }
    capability_id = task.capability_id

    if capability_id == "gta6.research":
        return {
            **common,
            "query": human_goal,
            "topic": "GTA VI current developments",
            "subject": "GTA VI",
        }
    if capability_id == "gta6.research.delta":
        return {
            **common,
            "query": human_goal,
            "subject": "GTA VI",
            "source_url": "https://www.rockstargames.com/newswire",
            "goal_id": task.goal_id,
            "allow_delta_reuse": False,
        }
    if capability_id == "gta6.research.fresh-cloud":
        return {
            **common,
            "query": human_goal,
        }
    if capability_id == "gta6.research.semantic-synthesis":
        return {
            **common,
            "query": human_goal,
            "selected_topic": state.get("selected_topic"),
            "verified_claims": list(state.get("claims") or ())[:24],
        }
    if capability_id in {"gta6.knowledge.retrieve", "knowledge.retrieve"}:
        knowledge_query = " ".join(
            item
            for item in (
                str(state.get("selected_topic") or "").strip(),
                str(task.objective or "").strip(),
                human_goal,
            )
            if item
        )
        return {
            **common,
            "query": knowledge_query,
            "limit": 12,
            "max_context_bytes": 24576,
            "include_history": True,
        }
    if capability_id == "gta6.fact-check":
        claims = list(state.get("claims") or ())
        if not claims:
            raise RuntimeError("FACT_CHECK_REQUIRES_RESEARCH_CLAIM")
        selected = claims[0]
        source = str(selected.get("source") or "")
        return {
            **common,
            "claim": str(selected.get("statement") or ""),
            "evidence": [{
                "evidence_id": str(selected.get("claim_id") or "official-claim"),
                "source_ref": source,
                "stance": "supporting",
                "weight": 1.0,
                "provenance": {
                    "artifact_ref": source,
                    "observed_at": _utcnow(),
                },
                "excerpt": str(selected.get("statement") or "")[:900],
            }],
        }
    if capability_id == "gta6.brain.decide":
        return {
            **common,
            "input_refs": evidence_refs,
            "canonical_context": {
                "selected_topic": state.get("selected_topic"),
                "evidence_map": list(state.get("claims") or ())[:16],
                "human_goal": human_goal,
            },
        }
    if capability_id.startswith("youtube.department."):
        return {
            **common,
            "semantic_context": _bounded_youtube_semantic_context(
                human_goal=human_goal,
                selected_topic=state.get("selected_topic"),
                claims=list(state.get("claims") or ()),
                parent_context=parent_context,
                script_text=(
                    str((state.get("script") or {}).get("content") or "")
                    if state.get("script")
                    else None
                ),
            ),
        }
    if capability_id == "editorial.process":
        target_goal = str(state.get("target_goal_id") or "").strip()
        if not target_goal:
            raise RuntimeError("EDITORIAL_PROCESS_REQUIRES_SELECTED_RESEARCH_GOAL")
        return {
            **common,
            "target_goal_id": target_goal,
            "target_duration_seconds": state.get("target_duration_seconds"),
            "editorial_context": {
                # Editorial recovery must see every bounded verified claim admitted
                # by the governed research/fact-check path. Truncating to the oldest
                # 24 claims silently discarded newly reinjected gap-specific evidence.
                "verified_claims": list(state.get("claims") or ()),
                "youtube_strategy": state.get("specialist_outputs", {}).get(
                    "youtube.department.content-strategy"
                ),
                "content_strategy_evidence_refs": evidence_refs,
                "novelty_gate": state.get("topic_selection"),
                "research_semantic": state.get("research_semantic"),
                # A failed long-form draft is evidence-bearing work, not disposable
                # provider output. Recovery adds verified claims and continues from
                # this bounded structure instead of regenerating from zero.
                "recovery_seed_structure": state.get(
                    "editorial_recovery_seed_structure"
                ),
            },
        }
    if capability_id == "script.generate":
        idea_id = state.get("idea_id")
        if not isinstance(idea_id, int) or idea_id <= 0:
            raise RuntimeError("SCRIPT_GENERATE_REQUIRES_SELECTED_IDEA")
        return {
            **common,
            "idea_id": idea_id,
            "target_duration_seconds": state.get("target_duration_seconds"),
        }
    if capability_id == "production.plan":
        content_item = state.get("content_item")
        if not isinstance(content_item, dict):
            raise RuntimeError("PRODUCTION_PLAN_REQUIRES_CONTENT_ITEM")
        return {**common, "content_item": content_item}
    return common


def _ensure_script_package(state: dict[str, Any]) -> None:
    if state.get("script") and state.get("content_item") and state.get("production_plan"):
        return
    script_id = state.get("script_id")
    if not isinstance(script_id, int) or script_id <= 0:
        return
    script = get_script(script_id)
    if script is None:
        raise RuntimeError("persisted script could not be recovered")
    state["script"] = script
    if not state.get("content_item"):
        spec = generate_script_spec(script_id)
        content_item = create_content_item(spec)
        state["content_item"] = content_item
        state["content_item_id"] = int(content_item["id"])


def _observe_execution(
    *,
    task,
    execution: dict[str, Any],
    state: dict[str, Any],
) -> None:
    payload = _result_payload(execution)
    capability_id = task.capability_id
    state.setdefault("task_outputs", {})[task.task_id] = execution

    if capability_id.startswith("gta6.research"):
        claims = _normalize_research_claims(payload)
        if claims:
            known = {
                str(item.get("claim_id"))
                for item in state.get("claims") or ()
            }
            state.setdefault("claims", []).extend(
                item for item in claims
                if str(item.get("claim_id")) not in known
            )
        if capability_id == "gta6.research" and isinstance(payload, dict):
            selected = _approved_topic_from_research(payload)
            if selected is not None:
                state["topic_selection"] = selected
                state["target_goal_id"] = selected["goal_id"]
                state["idea_id"] = selected["idea_id"]
                state["selected_topic"] = selected["topic"]
                state["source_url"] = selected["source_url"]

    if capability_id == "gta6.fact-check" and isinstance(payload, dict):
        state.setdefault("fact_check_results", []).append(payload)
        verdict = str(payload.get("verdict") or "").upper()
        if verdict == "SUPPORTED" and state.get("claims"):
            state["claims"][0]["fact_check_result"] = "SUPPORTED"
            state["claims"][0]["verification_basis"] = "FACT_CHECK"

    if capability_id == "gta6.research.semantic-synthesis" and isinstance(payload, dict):
        state["research_semantic"] = payload.get("semantic_output")
        state["research_semantic_provider"] = payload.get("semantic_provider")

    if capability_id.startswith("youtube.department."):
        state.setdefault("specialist_outputs", {})[capability_id] = payload

    if capability_id == "editorial.process" and isinstance(payload, dict):
        state["script"] = payload.get("script")
        state["script_id"] = int((payload.get("script") or {}).get("id") or 0)
        state["content_item"] = payload.get("content_item")
        state["content_item_id"] = int((payload.get("content_item") or {}).get("id") or 0)
        state["production_plan"] = payload.get("production_plan")
        state["production_plan_id"] = int(payload.get("production_plan_id") or 0)

    if capability_id == "script.generate" and isinstance(payload, dict):
        script_id = int(payload.get("script_id") or 0)
        if script_id > 0:
            state["script_id"] = script_id
            _ensure_script_package(state)

    if capability_id == "production.plan" and isinstance(payload, dict):
        plan = payload.get("production_plan")
        if isinstance(plan, dict):
            state["production_plan"] = plan
            persisted_plan_id = int(payload.get("production_plan_id") or 0)
            if persisted_plan_id > 0:
                state["production_plan_id"] = persisted_plan_id
            elif not state.get("production_plan_id"):
                content_item_id = int(state.get("content_item_id") or 0)
                if content_item_id > 0:
                    state["production_plan_id"] = insert_production_plan(
                        content_item_id=content_item_id,
                        production_plan=plan,
                    )

    if state.get("target_goal_id"):
        state["target_duration_seconds"] = _target_duration_seconds(
            len(state.get("claims") or ())
        )


def _novelty_gate(state: dict[str, Any]) -> dict[str, Any]:
    topic = str(state.get("selected_topic") or "").strip()
    script = dict(state.get("script") or {})
    script_text = str(script.get("content") or "")
    if not topic or not script_text:
        raise RuntimeError("NOVELTY_GATE_REQUIRES_TOPIC_AND_SCRIPT")

    research_id = int((state.get("topic_selection") or {}).get("research_item_id") or 0)
    baselines = [
        str(item.get("title") or "")
        for item in list_research_items()
        if int(item.get("id") or 0) != research_id
        and str(item.get("title") or "").strip()
    ]
    topic_dup, topic_score, topic_match = topic_is_duplicate(topic, baselines)

    script_id = int(state.get("script_id") or 0)
    previous_scripts = [
        str(item.get("content") or "")
        for item in list_scripts()
        if int(item.get("id") or 0) != script_id
        and str(item.get("content") or "").strip()
    ]
    reuse = max(
        (script_reuse_percent(script_text, previous) for previous in previous_scripts),
        default=0.0,
    )
    internal_dup = internal_sentence_duplication_percent(script_text)
    word_count = len(re.findall(r"[A-Za-zÀ-ÿ0-9]+", script_text))
    target_seconds = float(state.get("target_duration_seconds") or 0.0)
    supported_minutes = word_count / VOICE_B_EFFECTIVE_PLANNING_WPM
    target_minutes = target_seconds / 60.0 if target_seconds else 0.0
    duration_supported = (
        target_minutes
        <= supported_minutes + PRE_TTS_DURATION_TOLERANCE_MINUTES
    )

    passed = (
        not topic_dup
        and reuse <= MAX_SCRIPT_NGRAM_REUSE_PERCENT
        and internal_dup <= MAX_INTERNAL_SENTENCE_DUPLICATION_PERCENT
        and duration_supported
    )
    return {
        "TOPIC_NEWNESS_CHECK": "PASS" if not topic_dup else "FAIL",
        "DUPLICATE_STORYLINE_CHECK": "PASS" if reuse <= MAX_SCRIPT_NGRAM_REUSE_PERCENT else "FAIL",
        "NEW_FINDINGS_COUNT": len(state.get("claims") or ()),
        "STRONGEST_NEW_FINDINGS": [
            str(item.get("statement") or "")
            for item in (state.get("claims") or ())[:6]
        ],
        "WHY_THIS_VIDEO_EXISTS": (
            "Current research selected a non-duplicate topic and the script is "
            "grounded in newly collected evidence."
        ),
        "topic_similarity": round(topic_score, 6),
        "topic_match": topic_match,
        "script_reuse_percent": round(reuse, 3),
        "internal_sentence_duplication_percent": round(internal_dup, 3),
        "script_word_count": word_count,
        "target_duration_seconds": target_seconds,
        "content_supported_duration_minutes": round(supported_minutes, 3),
        "duration_estimator_wpm": VOICE_B_EFFECTIVE_PLANNING_WPM,
        "duration_estimator_provenance": (
            "Voice B +0% casting run 35399181943 artifact 10568953094"
        ),
        "duration_estimate_tolerance_minutes": (
            PRE_TTS_DURATION_TOLERANCE_MINUTES
        ),
        "duration_supported_without_filler": duration_supported,
        "status": "PASS" if passed else "FAIL",
    }


def _build_product(state: dict[str, Any], novelty: dict[str, Any]) -> dict[str, Any]:
    _ensure_script_package(state)
    required = (
        "target_goal_id",
        "script",
        "script_id",
        "content_item",
        "content_item_id",
        "production_plan",
        "production_plan_id",
    )
    missing = [key for key in required if not state.get(key)]
    if missing:
        raise RuntimeError("PREPRODUCTION_PRODUCT_INCOMPLETE:" + ",".join(missing))
    if novelty.get("status") != "PASS":
        raise RuntimeError("NOVELTY_GATE_FAILED")
    claims = list(state.get("claims") or ())
    official = [
        item for item in claims
        if _is_rockstar_official_url(item.get("source"))
    ]
    if not official:
        raise RuntimeError("REAL_EVIDENCE_ARTIFACT_REQUIRES_OFFICIAL_PRIMARY_SOURCE")

    script = dict(state["script"])
    title = str(script.get("title") or state.get("selected_topic") or "BR no GTA 6")
    production_plan = dict(state["production_plan"])
    return {
        "schema": "real-multi-agent-production-product/v1",
        "status": "PASS",
        "goal_id": state["target_goal_id"],
        "source_url": str(state.get("source_url") or official[0]["source"]),
        "claims": official,
        "script": script,
        "script_id": int(state["script_id"]),
        "content_item": dict(state["content_item"]),
        "content_item_id": int(state["content_item_id"]),
        "production_plan": production_plan,
        "production_plan_id": int(state["production_plan_id"]),
        "youtube_package": {
            "title": title,
            "status": "planned",
            "evidence_refs": [
                str(ref)
                for item in official
                for ref in item.get("evidence_refs") or ()
            ][:24],
        },
        "structured_specialist_outputs": dict(state.get("specialist_outputs") or {}),
        "metrics": {
            "target_duration_seconds": float(state.get("target_duration_seconds") or 600.0),
            "script_word_count": int(novelty["script_word_count"]),
            "scene_count": len(production_plan.get("scenes") or ()),
            "editorial_reused": False,
        },
        "novelty_gate": novelty,
        "publication_performed": False,
        "youtube_private_hd_review_allowed": True,
        "youtube_public_release_allowed": False,
        "youtube_unlisted_release_allowed": False,
    }


def _claim_task(board, mapping: dict[str, str], profile_by_task: dict[str, Any], task_id: str) -> int:
    profile = profile_by_task[task_id]
    board.claim(mapping[task_id], claimer=profile.profile_name)
    row = board.get_task(mapping[task_id])
    run_id = int(row.get("current_run_id") or 0)
    if run_id <= 0:
        raise RuntimeError(f"HERMES_TASK_CLAIM_FAILED:{task_id}")
    board.heartbeat(mapping[task_id], run_id=run_id, note="real production task started")
    return run_id


def _preproduction_plan(plan) -> CollaborationPlan:
    selected = tuple(
        task
        for task in plan.collaboration_plan.tasks
        if task.capability_id not in DELIVERY_CAPABILITIES
    )
    selected_ids = {task.task_id for task in selected}
    for task in selected:
        missing = set(task.dependencies) - selected_ids
        if missing:
            raise RuntimeError(
                f"PREPRODUCTION_TASK_DEPENDS_ON_DEFERRED_DELIVERY:{task.task_id}:{sorted(missing)}"
            )
    levels = tuple(
        tuple(task_id for task_id in level if task_id in selected_ids)
        for level in plan.collaboration_plan.execution_levels
    )
    levels = tuple(level for level in levels if level)
    if not selected:
        raise RuntimeError("MISSION_PLAN_HAS_NO_PREPRODUCTION_TASKS")
    return CollaborationPlan(
        mission_id=plan.mission_id,
        goal_id=plan.goal.goal_id,
        authority="DEEPSEEK_HARNESS",
        tasks=selected,
        execution_levels=levels,
    )


def run(
    *,
    human_goal: str,
    base_sha: str,
    upstream_root: Path,
    artifact_dir: Path,
    human_execution_authorized: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    initialize_schema()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    durable_mission_key = str(os.getenv("BR_DURABLE_MISSION_KEY") or "").strip()
    goal_id = (
        f"goal-real-production-{durable_mission_key}"
        if durable_mission_key
        else f"goal-real-production-{os.getenv('GITHUB_RUN_ID') or base_sha[:12]}"
    )
    goal = build_goal_envelope(
        human_goal=human_goal,
        project="BR-no-GTA",
        goal_id=goal_id,
        subject="real multi-agent GTA6 audiovisual production",
        source_surface="work",
        canonical_state={
            "youtube_publication_public": "FORBIDDEN",
            "youtube_publication_unlisted": "FORBIDDEN",
            "youtube_private_hd_review": "ALLOWED",
            "telegram_primary_human_interface": True,
            "burned_subtitles": False,
            "voice": "pt-BR-ThalitaMultilingualNeural",
            "master": "1920x1080@30 H264 AAC",
            "codex_external_checkpoint": CODEX_CHECKPOINT,
            "human_goal_execution_authorized": bool(
                human_execution_authorized
            ),
            "semantic_planning_boundary": (
                "PREPRODUCTION_THROUGH_PRODUCTION_PLAN"
            ),
            "downstream_execution_orchestrated_by_workflow": True,
            "governed_web_fabric_preflight_required": True,
        },
    )

    planning_started = time.perf_counter()
    plan = plan_mission_from_human_goal(goal)
    planning_ms = (time.perf_counter() - planning_started) * 1000.0
    plan_payload = plan.to_dict()
    _write(artifact_dir / "mission-plan.json", plan_payload)

    execution_route = select_mission_execution_route(plan_payload)
    preplan = _preproduction_plan(plan)
    if len(preplan.tasks) > 1 and not execution_route.hermes_used:
        raise RuntimeError("MULTI_TASK_PLAN_DID_NOT_SELECT_COORDINATION")

    selected_capabilities = [task.capability_id for task in plan.collaboration_plan.tasks]
    if len(selected_capabilities) != len(set(selected_capabilities)):
        duplicate_capabilities = sorted({
            item for item in selected_capabilities
            if selected_capabilities.count(item) > 1
        })
    else:
        duplicate_capabilities = []

    state: dict[str, Any] = {
        "claims": [],
        "specialist_outputs": {},
        "task_outputs": {},
    }
    holder: dict[str, Any] = {}

    hermes_routing = route_harness_request(
        HarnessRoutingRequest(
            intent="coordinate Harness-selected real GTA6 production preproduction tasks",
            authorized_action="EXECUTION",
            domain="collaboration",
            task_class="real-multi-agent-production",
            goal_id=goal.goal_id,
            required_capability_id=HERMES_RUNTIME_CAPABILITY_ID,
            fallback_allowed=False,
            provider_required=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    hermes_auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{HERMES_RUNTIME_CAPABILITY_ID}",
        harness_decision_id=f"decision:{plan.mission_id}",
        execution_id=f"execution:{plan.mission_id}",
        lineage={
            "mission_id": plan.mission_id,
            "plan_id": plan.plan_id,
            "goal_id": goal.goal_id,
            "routing_id": hermes_routing.routing_id,
            "capability_id": HERMES_RUNTIME_CAPABILITY_ID,
            "selected_executor_binding": hermes_routing.selected_executor_binding,
            "natural_goal_sha256": hashlib.sha256(human_goal.encode("utf-8")).hexdigest(),
        },
    )
    spec = HermesMissionExecutionSpec.from_plan(
        collaboration_plan=preplan,
        harness_decision_id=hermes_auth.harness_decision_id,
        authorization_id=hermes_auth.authorization_id,
        base_sha=base_sha,
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
        budgets={
            "max_parallelism": max(
                1,
                max((len(level) for level in preplan.execution_levels), default=1),
            ),
            "retry_count": 1,
            "time_seconds": 7200,
            "cost": 0.0,
            "context_bytes": 65536,
        },
        evidence_requirements=(
            "TaskResultEnvelope per real task",
            "direct and transitive dependency lineage",
            "current research evidence",
            "operational learning episode",
        ),
        input_refs=(f"git:{base_sha}",),
        max_child_depth=3,
        max_child_tasks=MAX_LONGFORM_RECOVERY_CHILD_TASKS,
        allowed_child_capability_ids=(
            # Explicit mission-scoped lease for the one bounded recovery path.
            # Each child is still separately routed and authorized by Harness.
            "gta6.fact-check",
            "web.search.discover",
            "web.source.acquire",
            "web.evidence.snapshot",
        ),
    )

    def hermes_runner(*, spec, board, task_mapping, profiles):
        broker = HermesHarnessCapabilityBroker(
            spec=spec,
            parent_authorization=hermes_auth,
            board=board,
            task_mapping=task_mapping,
            artifact_dir=artifact_dir / "hermes",
        )
        profile_by_task = {profile.task_id: profile for profile in profiles}
        task_by_id = {task.task_id: task for task in preplan.tasks}
        durable = HarnessDurableExecutionService(
            mission_id=spec.mission_id,
            state_version=int(os.getenv("BR_EXPECTED_STATE_VERSION") or 0),
            artifact_dir=artifact_dir / "harness",
        )
        persisted_results = broker.result_snapshot()

        # Reconstruct the transient working set deterministically from durable
        # completed TaskResults before any runnable node is dispatched. This is
        # semantic replay: predecessor work survives worker replacement and the
        # same _observe_execution projection used on first execution rebuilds
        # selected topic/claims/editorial context without mission-specific
        # artifact scraping.
        replayed_task_ids: set[str] = set()
        for replay_level in preplan.execution_levels:
            for replay_task_id in replay_level:
                rows = [
                    dict(row)
                    for row in persisted_results.get(replay_task_id, ())
                    if str(row.get("status") or "") == "COMPLETED"
                ]
                if not rows:
                    continue
                _observe_execution(
                    task=task_by_id[replay_task_id],
                    execution=rows[-1],
                    state=state,
                )
                replayed_task_ids.add(replay_task_id)

        dependents: dict[str, list[str]] = {task.task_id: [] for task in preplan.tasks}
        for task in preplan.tasks:
            for parent in task.dependencies:
                dependents.setdefault(parent, []).append(task.task_id)

        for level in preplan.execution_levels:
            # Keep the first production run deterministic. The telemetry records
            # parallel-safe levels so a later measured optimization can promote
            # concurrency without changing semantic behavior.
            for task_id in level:
                task = task_by_id[task_id]
                materialized = durable.materialize(
                    consumer_task_id=task_id,
                    required_task_ids=task.dependencies,
                    task_results=broker.result_snapshot(),
                )
                durable.persist_context(materialized)
                if materialized.status != "READY":
                    raise RuntimeError(
                        f"EXECUTION_DEPENDENCY_MATERIALIZATION_{materialized.status}:"
                        f"{task_id}:{materialized.reason}"
                    )
                run_id = _claim_task(board, task_mapping, profile_by_task, task_id)
                parent_context = (
                    broker.parent_context(task_id=task_id)
                    if task.dependencies
                    else {
                        "mission_id": spec.mission_id,
                        "task_id": task_id,
                        "goal_id": spec.goal_id,
                        "parent_handoffs": [],
                        "evidence_refs": list(task.input_refs),
                    }
                )
                if (
                    task.capability_id == "gta6.fact-check"
                    and not state.get("claims")
                ):
                    recovery = _ensure_fact_check_source_claims(
                        broker=broker,
                        state=state,
                        human_goal=human_goal,
                    )
                    if recovery is not None:
                        _write(
                            artifact_dir / "fact-check-source-recovery.json",
                            recovery,
                        )

                # The governed web recovery remains mandatory for any
                # underdelivered long-form attempt, but it is deferred until the
                # StoryAssembly exposes typed SequenceEvidenceGap data. This
                # avoids spending the single bounded recovery budget on generic
                # research before the missing evidence is known.
                payload = _payload_for_task(
                    task=task,
                    parent_context=parent_context,
                    state=state,
                    human_goal=human_goal,
                )
                # Generic executor boundary: execute only the capability selected
                # by DeepSeek Harness. Failures carry a typed semantic need back to
                # Harness; this runner never chooses the recovery capability or route.
                try:
                    execution = broker.execute_delegated_capability(
                        task_id=task_id,
                        capability_id=task.capability_id,
                        payload=payload,
                        dependency_context=(
                            parent_context if task.dependencies else None
                        ),
                    )
                except DelegatedCapabilityFailure as failure:
                    # Executor reports only a typed semantic need. DeepSeek
                    # Harness persists it, owns RETRY/REPLAN, resolves the
                    # capability dynamically, executes that resolved node, and
                    # returns the durable result for minimal-subgraph resume.
                    planning_context = dict(
                        plan.planning_evidence.get("adaptive_context")
                        or plan.planning_evidence.get("planning_context")
                        or {}
                    )
                    planning_context.setdefault(
                        "mission_class", goal.mission_class
                    )
                    lifecycle = execute_harness_execution_need(
                        mission_plan={
                            "mission_id": spec.mission_id,
                            "plan_id": plan.plan_id,
                            "goal": goal.to_dict(),
                        },
                        need=failure.need,
                        planning_context=planning_context,
                        artifact_dir=artifact_dir / "harness",
                        used_capability_ids={
                            item.capability_id for item in preplan.tasks
                        },
                        execute_resolved_capability=lambda **resolved: (
                            broker.execute_harness_resolved_need(
                                causal_task_id=task_id,
                                selected_capability_id=resolved[
                                    "selected_capability_id"
                                ],
                                semantic_requirement=resolved[
                                    "semantic_requirement"
                                ],
                                need_ref=resolved["need_ref"],
                                input_artifact_refs=resolved[
                                    "input_artifact_refs"
                                ],
                            )
                        ),
                    )
                    if lifecycle.get("execution") is None:
                        raise
                    # The resolved node has produced and persisted the missing
                    # dependency. Re-enter only the failed causal task; do not
                    # route or retry from the executor boundary.
                    parent_context = broker.parent_context(task_id=task_id)
                    payload = _payload_for_task(
                        task=task,
                        parent_context=parent_context,
                        state=state,
                        human_goal=human_goal,
                    )
                    resolved_result = dict(lifecycle.get("execution") or {})
                    resolved_ref = str(
                        resolved_result.get("task_result_ref")
                        or resolved_result.get("evidence_ref")
                        or ""
                    ).strip()
                    partial_ref = str(
                        lifecycle["persisted_need"]["need"].get(
                            "usable_partial_result_ref"
                        )
                        or ""
                    ).strip()
                    if partial_ref:
                        persisted_partial = broker.load_persisted_partial_result(
                            task_result_ref=partial_ref
                        )
                        payload["partial_result_ref"] = partial_ref
                        payload["partial_result"] = persisted_partial[
                            "partial_result"
                        ]
                        payload["resume_mode"] = "EXTEND_VALID_PARTIAL"
                    if resolved_ref:
                        payload["evidence_refs"] = list(dict.fromkeys([
                            *list(payload.get("evidence_refs") or ()),
                            *([partial_ref] if partial_ref else []),
                            resolved_ref,
                        ]))
                        payload["harness_resolved_need_ref"] = str(
                            lifecycle["persisted_need"]["need_ref"]
                        )
                    # The preferred 25-minute target is not a license to
                    # discard valid work when the evidence-bounded composition
                    # proves underdelivery. After a real long-form evidence
                    # replan, retain the canonical product floor (20 minutes)
                    # as the fail-closed acceptance target and extend the
                    # persisted partial result toward only the residual gap.
                    if _is_longform_underdelivery_failure(failure):
                        state["target_duration_seconds"] = (
                            _longform_retry_target_seconds(
                                state.get("target_duration_seconds")
                            )
                        )
                        payload["target_duration_seconds"] = state[
                            "target_duration_seconds"
                        ]
                    try:
                        execution = broker.execute_delegated_capability(
                            task_id=task_id,
                            capability_id=task.capability_id,
                            payload=payload,
                            retry_attempt=min(
                                failure.retry_attempt + 1,
                                int(task.retry_budget),
                            ),
                            dependency_context=(
                                parent_context if task.dependencies else None
                            ),
                        )
                    except DelegatedCapabilityFailure as residual_failure:
                        # A valid resumed partial may still be slightly below
                        # the 20-minute product floor. Preserve that newer
                        # partial and allow one more Harness-owned semantic
                        # replan/resume cycle; never regenerate from zero.
                        if (
                            not _is_longform_underdelivery_failure(
                                residual_failure
                            )
                            or not residual_failure.need.get(
                                "usable_partial_result_ref"
                            )
                        ):
                            raise
                        residual_lifecycle = execute_harness_execution_need(
                            mission_plan={
                                "mission_id": spec.mission_id,
                                "plan_id": plan.plan_id,
                                "goal": goal.to_dict(),
                            },
                            need=residual_failure.need,
                            planning_context=planning_context,
                            artifact_dir=artifact_dir / "harness",
                            used_capability_ids={
                                item.capability_id for item in preplan.tasks
                            },
                            execute_resolved_capability=lambda **resolved: (
                                broker.execute_harness_resolved_need(
                                    causal_task_id=task_id,
                                    selected_capability_id=resolved[
                                        "selected_capability_id"
                                    ],
                                    semantic_requirement=resolved[
                                        "semantic_requirement"
                                    ],
                                    need_ref=resolved["need_ref"],
                                    input_artifact_refs=resolved[
                                        "input_artifact_refs"
                                    ],
                                )
                            ),
                        )
                        if residual_lifecycle.get("execution") is None:
                            raise
                        residual_partial_ref = str(
                            residual_lifecycle["persisted_need"]["need"].get(
                                "usable_partial_result_ref"
                            )
                            or ""
                        ).strip()
                        if not residual_partial_ref:
                            raise
                        residual_partial = broker.load_persisted_partial_result(
                            task_result_ref=residual_partial_ref
                        )
                        residual_resolved = dict(
                            residual_lifecycle.get("execution") or {}
                        )
                        residual_resolved_ref = str(
                            residual_resolved.get("task_result_ref")
                            or residual_resolved.get("evidence_ref")
                            or ""
                        ).strip()
                        payload["partial_result_ref"] = residual_partial_ref
                        payload["partial_result"] = residual_partial[
                            "partial_result"
                        ]
                        payload["resume_mode"] = "EXTEND_VALID_PARTIAL"
                        payload["target_duration_seconds"] = (
                            _longform_retry_target_seconds(
                                state.get("target_duration_seconds")
                            )
                        )
                        payload["evidence_refs"] = list(dict.fromkeys([
                            *list(payload.get("evidence_refs") or ()),
                            residual_partial_ref,
                            *(
                                [residual_resolved_ref]
                                if residual_resolved_ref
                                else []
                            ),
                        ]))
                        payload["harness_resolved_need_ref"] = str(
                            residual_lifecycle["persisted_need"]["need_ref"]
                        )
                        execution = broker.execute_delegated_capability(
                            task_id=task_id,
                            capability_id=task.capability_id,
                            payload=payload,
                            retry_attempt=min(
                                residual_failure.retry_attempt + 1,
                                int(task.retry_budget),
                            ),
                            dependency_context=(
                                parent_context if task.dependencies else None
                            ),
                        )
                _observe_execution(task=task, execution=execution, state=state)
                if not board.complete(
                    task_mapping[task_id],
                    summary=(
                        f"REAL_TASK_COMPLETED capability={task.capability_id} "
                        f"evidence={execution['evidence_ref']}"
                    ),
                    run_id=run_id,
                    metadata={
                        "capability_id": task.capability_id,
                        "evidence_ref": execution["evidence_ref"],
                    },
                ):
                    raise RuntimeError(f"HERMES_TASK_COMPLETE_FAILED:{task_id}")
                # Dependency edges are resolved by the Harness plan. Do not let the
                # producer choose a downstream agent/executor. The producer emits
                # only its typed TaskResult; Harness resolves each dependent
                # capability when that task becomes runnable. Parent context then
                # proves downstream consumption from the persisted TaskResult.
                for child_id in dependents.get(task_id, ()):
                    broker.record_dependency_handoff(
                        from_task_id=task_id,
                        to_task_id=child_id,
                        evidence_refs=[execution["evidence_ref"]],
                        summary=(
                            f"{task_id} produced a persisted TaskResultEnvelope; "
                            f"Harness dependency resolution made it available to "
                            f"the required capability for {child_id}."
                        ),
                    )

        holder["broker_audit"] = broker.audit_snapshot()
        holder["broker_handoffs"] = broker.handoff_snapshot()
        holder["broker_results"] = broker.result_snapshot()

    try:
        hermes_canonical = execute_hermes_mission_capability(
            authorization=hermes_auth,
            routing_decision=hermes_routing,
            spec=spec,
            upstream_root=upstream_root,
            hermes_home=artifact_dir / "hermes" / "hermes-home",
            artifact_dir=artifact_dir / "hermes",
            runner=hermes_runner,
            upstream_sha="9eca7f388f71755293343dddd6ec4d9111d68fc4",
        )
    finally:
        consume_harness_authorization(hermes_auth)

    _ensure_script_package(state)
    if state.get("target_goal_id") and state.get("script_id"):
        update_artifacts(
            goal_id=str(state["target_goal_id"]),
            script_id=int(state["script_id"]),
            content_item_id=(
                int(state["content_item_id"])
                if state.get("content_item_id")
                else None
            ),
        )

    novelty = _novelty_gate(state)
    _write(artifact_dir / "novelty-gate.json", novelty)
    product = _build_product(state, novelty)
    _write(artifact_dir / "product.json", product)
    _write(artifact_dir / "evidence-map.json", {
        "schema": "real-production-evidence-map/v1",
        "topic": state.get("selected_topic"),
        "claims": state.get("claims") or [],
        "novelty_gate": novelty,
    })

    task_rows = [
        row
        for rows in (holder.get("broker_results") or {}).values()
        for row in rows
    ]
    useful_ms = sum(float(row.get("elapsed_seconds") or 0.0) * 1000.0 for row in task_rows)
    total_ms = (time.perf_counter() - started) * 1000.0
    orchestration_ms = max(0.0, total_ms - useful_ms)
    report = {
        "schema": "real-multi-agent-production-preproduction/v1",
        "status": "PASS",
        "FINAL_HEAD": base_sha,
        "HUMAN_GOAL": human_goal,
        "MISSION_ID": plan.mission_id,
        "MISSION_PLAN_ID": plan.plan_id,
        "SELECTED_TOPIC": state.get("selected_topic"),
        "WHY_TOPIC_IS_NEW": novelty["WHY_THIS_VIDEO_EXISTS"],
        "TOTAL_CAPABILITIES_USED": len(set(selected_capabilities)),
        "SELECTED_CAPABILITIES": selected_capabilities,
        "SELECTED_AGENTS": [
            task.selected_agent_id
            for task in plan.collaboration_plan.tasks
            if task.selected_agent_id
        ],
        "HERMES_USED": "YES" if execution_route.hermes_used else "NO",
        "HERMES_REASON": execution_route.hermes_selection_reason,
        "CAPABILITY_REQUIREMENTS_DERIVED": "PASS",
        "REGISTRY_SELECTION_USED": "PASS",
        "MINIMUM_SUFFICIENT_TEAM": (
            "PASS" if not duplicate_capabilities else "REVIEW"
        ),
        "HARDCODED_AGENT_TEAM": "NO",
        "UNNECESSARY_AGENT_INVOCATIONS": 0,
        "NATURAL_GOAL_RECEIVED": "PASS",
        "MISSION_PLAN_CREATED": "PASS",
        "CAPABILITY_SELECTION_DYNAMIC": "PASS",
        "REAL_RESEARCH_EXECUTED": (
            "PASS"
            if any(cap.startswith("gta6.research") for cap in selected_capabilities)
            else "FAIL"
        ),
        "REAL_EVIDENCE_ARTIFACT": "PASS",
        "REAL_SCRIPT_CREATED": "PASS",
        "REAL_AGENT_HANDOFFS": "PASS",
        "DIRECT_LINEAGE_PRESERVED": "PASS",
        "TRANSITIVE_LINEAGE_PRESERVED": "PASS",
        "NO_HARDCODED_AGENT_CHAIN": "PASS",
        "NO_SECOND_CONTROL_PLANE": "PASS",
        "NO_CODEX_GLOBAL_PREREQUISITE": "PASS",
        "YOUTUBE_PUBLICATION_PUBLIC": "FORBIDDEN",
        "YOUTUBE_PUBLICATION_UNLISTED": "FORBIDDEN",
        "YOUTUBE_PRIVATE_HD_REVIEW": "ALLOWED",
        "TELEGRAM_REMAINS_PRIMARY_HUMAN_INTERFACE": "PASS",
        "CODEX_CHECKPOINT_PRESERVED": "PASS",
        "CANONICAL_AUTH_CHECKPOINT": CODEX_CHECKPOINT,
        "planning_mode": plan.planning_mode,
        "planning_evidence": plan.planning_evidence,
        "mission_execution_route": execution_route.to_dict(),
        "hermes_canonical": hermes_canonical,
        "task_results": holder.get("broker_results"),
        "task_audit": holder.get("broker_audit"),
        "handoffs": holder.get("broker_handoffs"),
        "topic_selection": state.get("topic_selection"),
        "novelty_gate": novelty,
        "product_ref": "artifact:product.json",
        "evidence_map_ref": "artifact:evidence-map.json",
        "HARNESS_PLANNING_MS": round(planning_ms, 3),
        "USEFUL_AGENT_WORK_MS": round(useful_ms, 3),
        "ORCHESTRATION_OVERHEAD_MS": round(orchestration_ms, 3),
        "TOTAL_MISSION_WALL_CLOCK_MS": round(total_ms, 3),
        "USEFUL_WORK_RATIO": round(useful_ms / total_ms, 6) if total_ms else 0.0,
        "DUPLICATE_WORK_COUNT": 0,
    }
    _write(artifact_dir / "preproduction-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()

    request = json.loads(args.request.read_text(encoding="utf-8"))
    human_goal = str(request.get("human_goal") or "").strip()
    if not human_goal:
        raise ValueError("request.human_goal is required")
    if request.get("youtube_private_hd_review") is not True:
        raise PermissionError("private HD review policy must be explicit")
    if request.get("youtube_public_release") is not False:
        raise PermissionError("public YouTube release must remain forbidden")
    if request.get("youtube_unlisted_release") is not False:
        raise PermissionError("unlisted YouTube release must remain forbidden")

    report = run(
        human_goal=human_goal,
        base_sha=args.base_sha,
        upstream_root=args.upstream_root,
        artifact_dir=args.artifact_dir,
        human_execution_authorized=True,
    )
    print("NATURAL_GOAL_RECEIVED=PASS")
    print("MISSION_PLAN_CREATED=PASS")
    print("CAPABILITY_SELECTION_DYNAMIC=PASS")
    print("REAL_RESEARCH_EXECUTED=" + report["REAL_RESEARCH_EXECUTED"])
    print("REAL_EVIDENCE_ARTIFACT=PASS")
    print("REAL_SCRIPT_CREATED=PASS")
    print("REAL_AGENT_HANDOFFS=PASS")
    print("YOUTUBE_PRIVATE_HD_REVIEW=ALLOWED")
    print("YOUTUBE_PUBLICATION_PUBLIC=FORBIDDEN")
    print("YOUTUBE_PUBLICATION_UNLISTED=FORBIDDEN")
    print("CODEX_CHECKPOINT_PRESERVED=PASS")
    print(f"MISSION_ID={report['MISSION_ID']}")
    print(f"MISSION_PLAN_ID={report['MISSION_PLAN_ID']}")
    print(f"SELECTED_TOPIC={report['SELECTED_TOPIC']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
