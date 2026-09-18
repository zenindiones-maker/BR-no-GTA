from __future__ import annotations

import app.services.telegram_learning_service as telegram_learning_service
import app.services.telegram_source_intelligence_service as source_intelligence_service

from app.database.telegram_source_intelligence_repository import (
    get_editorial_signal_by_candidate,
    get_source_candidate_by_input,
    list_source_claims,
)
from app.services.telegram_fresh_research_service import (
    FreshResearchEvidence,
    requires_fresh_research,
)
from app.services.telegram_learning_service import ingest_telegram_input_under_harness
from app.services.telegram_source_intelligence_service import (
    process_telegram_source_intelligence,
)
from scripts.gta6_fresh_research_worker import _secondary_hierarchy
from scripts.telegram_harness_gateway_v2 import (
    _chat_reply_v2,
    _conversation_classification_override,
    _source_evidence_payload,
)


CHECKED_AT = "2026-09-18T15:00:00+00:00"


def _ingest(url: str, *, message_id: int = 9001):
    result = ingest_telegram_input_under_harness(
        {
            "telegram_user_id": 111,
            "telegram_chat_id": 111,
            "telegram_message_id": message_id,
            "telegram_update_id": message_id + 1000,
            "input_kind": "text",
            "text": f"Confira esta fonte sobre GTA VI: {url}",
        }
    )
    return result["input"]


def _official_source(name: str, url: str, excerpt: str):
    return {
        "source_name": name,
        "url": url,
        "resolved_url": url,
        "authority": "official",
        "source_hierarchy": "OFFICIAL_PRIMARY",
        "original_source": True,
        "checked_at": CHECKED_AT,
        "content_excerpt": excerpt,
        "content_fingerprint": name.lower().replace(" ", "-"),
        "independent_group": "rockstargames.com",
    }


def _fresh(packet: dict) -> FreshResearchEvidence:
    return FreshResearchEvidence(
        status="PASS",
        authority="deepseek_harness",
        routing_id="route-real-source-test",
        authorization_id="auth-real-source-test",
        execution_id="research-real-source-test",
        checked_at=CHECKED_AT,
        official_source_count=len(packet.get("official_sources") or []),
        secondary_source_count=len(packet.get("secondary_sources") or []),
        packet=packet,
        execution_ref="github-actions:test-source-run",
    )


def _base_packet(submitted: dict) -> dict:
    unrelated = "Official Rockstar Games information about GTA VI, Vice City, Lucia and Jason."
    return {
        "status": "PASS",
        "execution_id": "research-real-source-test",
        "query": "GTA VI source verification",
        "checked_at": CHECKED_AT,
        "official_source_count": 3,
        "secondary_source_count": 0,
        "submitted_source": submitted,
        "source_content_resolution": submitted["resolution_status"],
        "official_sources": [
            _official_source("Rockstar GTA VI", "https://www.rockstargames.com/VI", unrelated),
            _official_source("Rockstar Store GTA VI", "https://store.rockstargames.com/game/buy-gta-vi", unrelated),
            _official_source("Rockstar Newswire", "https://www.rockstargames.com/newswire", unrelated),
        ],
        "secondary_sources": [],
        "source_errors": [],
        "policy": {
            "official_primary_requires_direct_artifact": True,
            "primary_statement_reported_by_secondary_is_not_official_primary": True,
            "multiple_independent_reports_require_distinct_origin_groups": True,
            "duplicate_content_fingerprints_are_not_independent": True,
            "social_links_require_original_content_resolution": True,
        },
    }


def test_structured_news_and_urls_force_fresh_research():
    assert requires_fresh_research(
        "olha isso",
        input_context={
            "classification": "news",
            "input_kind": "text",
            "source_url": "https://example.com/story",
        },
    )
    assert requires_fresh_research(
        "sem palavras de atualidade https://example.com/story"
    )
    assert requires_fresh_research(
        "conteúdo externo",
        input_context={"input_kind": "social_link"},
    )


def test_url_ingress_is_source_candidate_not_semantic_memory():
    record = _ingest("https://example.com/gta-vi")
    assert record["classification"] == "news"
    assert record["learning_status"] == "captured"
    assert record["source_state"] == "SOURCE_CANDIDATE"
    assert record["source_url"] == "https://example.com/gta-vi"
    assert record["claim_id"] is None
    assert record["memory_id"] is None
    candidate = get_source_candidate_by_input(record["id"])
    assert candidate is not None
    assert candidate["source_state"] == "SOURCE_CANDIDATE"


def test_news_ingress_never_calls_semantic_memory_persistence(monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError("news ingress must not create semantic claim/memory")

    monkeypatch.setattr(
        telegram_learning_service,
        "_persist_memory_learning",
        forbidden,
    )
    record = _ingest("https://example.com/news-only-candidate", message_id=9008)
    assert record["classification"] == "news"
    assert record["learning_status"] == "captured"
    assert record["source_state"] == "SOURCE_CANDIDATE"
    assert record["claim_id"] is None
    assert record["memory_id"] is None


def test_semantic_promotion_happens_only_after_source_candidate_is_verified(monkeypatch):
    url = "https://www.rockstargames.com/VI/causal-proof"
    record = _ingest(url, message_id=9009)
    claim = (
        "Rockstar confirms that GTA VI follows Lucia and Jason across Vice City "
        "and the state of Leonida."
    )
    packet = _base_packet(
        {
            "resolution_status": "PASS",
            "source_name": "Rockstar GTA VI",
            "url": url,
            "resolved_url": url,
            "platform": "web",
            "retrieved_at": CHECKED_AT,
            "source_hierarchy": "OFFICIAL_PRIMARY",
            "original_source_retrieved": True,
            "content_excerpt": claim,
            "content_sha256": "d" * 64,
            "independent_group": "rockstargames.com",
            "content_fingerprint": "official-causal-proof",
        }
    )
    packet["official_sources"][0]["content_excerpt"] = claim

    observed_states = []
    original = source_intelligence_service._promote_verified_claim

    def guarded_promote(**kwargs):
        current = get_source_candidate_by_input(record["id"])
        assert current is not None
        observed_states.append(current["source_state"])
        assert current["source_state"] == "VERIFIED"
        return original(**kwargs)

    monkeypatch.setattr(
        source_intelligence_service,
        "_promote_verified_claim",
        guarded_promote,
    )
    result = process_telegram_source_intelligence(
        input_record=record,
        fresh_evidence=_fresh(packet),
    )
    assert observed_states == ["VERIFIED"]
    assert result["INPUT_CAPTURED"] == "PASS"
    assert result["SOURCE_LEARNED"] == "PASS"
    assert result["CLAIM_VERIFIED"] == "PASS"
    assert result["SEMANTIC_MEMORY_PROMOTED"] == "PASS"
    assert result["source_candidate"]["source_state"] == "MEMORY_ELIGIBLE"


def test_direct_official_source_verifies_before_memory_and_creates_signal():
    url = "https://www.rockstargames.com/VI"
    record = _ingest(url, message_id=9002)
    claim = (
        "Rockstar confirms that GTA VI follows Lucia and Jason across Vice City "
        "and the state of Leonida."
    )
    packet = _base_packet(
        {
            "resolution_status": "PASS",
            "source_name": "Rockstar GTA VI",
            "url": url,
            "resolved_url": url,
            "platform": "web",
            "retrieved_at": CHECKED_AT,
            "source_hierarchy": "OFFICIAL_PRIMARY",
            "original_source_retrieved": True,
            "content_excerpt": claim,
            "content_sha256": "a" * 64,
            "independent_group": "rockstargames.com",
            "content_fingerprint": "official-direct",
        }
    )
    packet["official_sources"][0]["content_excerpt"] = claim

    result = process_telegram_source_intelligence(
        input_record=record,
        fresh_evidence=_fresh(packet),
    )

    assert result["REAL_TELEGRAM_SOURCE_INPUT"] == "PASS"
    assert result["INPUT_CAPTURED"] == "PASS"
    assert result["SOURCE_LEARNED"] == "PASS"
    assert result["CLAIM_VERIFIED"] == "PASS"
    assert result["SOURCE_CONTENT_RESOLVED"] == "PASS"
    assert result["CLAIMS_EXTRACTED"] == "PASS"
    assert result["FACT_CHECK_EXECUTED"] == "PASS"
    assert result["SOURCE_HIERARCHY_ENFORCED"] == "PASS"
    assert result["UNVERIFIED_CLAIM_NOT_PROMOTED"] == "PASS"
    assert result["SEMANTIC_MEMORY_PROMOTED"] == "PASS"
    assert result["EDITORIAL_SIGNAL_CREATED"] == "PASS"
    assert result["HUMAN_INPUT_LINEAGE_PRESERVED"] == "PASS"

    candidate = result["source_candidate"]
    states = [item["state"] for item in candidate["state_history"]]
    assert states == [
        "SOURCE_CANDIDATE",
        "FETCHED",
        "CLAIMS_EXTRACTED",
        "FACT_CHECKED",
        "VERIFIED",
        "MEMORY_ELIGIBLE",
    ]
    assert len(result["claim_ledger"]) == 1
    assert result["claim_ledger"][0]["fact_check_result"] == "SUPPORTED"
    assert result["claim_ledger"][0]["script_eligible"] is True
    claims = list_source_claims(candidate["candidate_id"])
    assert len(claims) == 1
    assert claims[0]["verification_status"] == "VERIFIED"
    assert claims[0]["source_hierarchy"] == "OFFICIAL_PRIMARY"
    assert claims[0]["semantic_memory_id"] is not None

    signal = get_editorial_signal_by_candidate(candidate["candidate_id"])
    assert signal is not None
    assert signal["harness_decision"] == "STORE_FOR_FUTURE"
    assert signal["payload"]["telegram_input_id"] == record["id"]
    assert signal["payload"]["memory_event_id"] == record["memory_event_id"]

    debug = _source_evidence_payload(record["id"])
    assert debug["INPUT_CAPTURED"] == "PASS"
    assert debug["SOURCE_LEARNED"] == "PASS"
    assert debug["CLAIM_VERIFIED"] == "PASS"
    assert debug["SEMANTIC_MEMORY_PROMOTED"] == "PASS"
    assert debug["EDITORIAL_SIGNAL_CREATED"] == "PASS"


def test_copied_secondary_reports_do_not_become_independent_confirmation():
    url = "https://news.example.com/gta-vi-report"
    record = _ingest(url, message_id=9003)
    claim = (
        "A report says Rockstar confirms GTA VI will include a new system in Vice City."
    )
    packet = _base_packet(
        {
            "resolution_status": "PASS",
            "source_name": "Example News",
            "url": url,
            "resolved_url": url,
            "platform": "web",
            "retrieved_at": CHECKED_AT,
            "source_hierarchy": "SECONDARY_REPORT",
            "original_source_retrieved": True,
            "content_excerpt": claim,
            "content_sha256": "b" * 64,
            "independent_group": "example.com",
            "content_fingerprint": "same-origin-copy",
        }
    )
    packet["secondary_source_count"] = 2
    packet["secondary_sources"] = [
        {
            "source_name": "Outlet A",
            "title": claim,
            "summary": claim,
            "url": "https://a.example/report",
            "published_at": CHECKED_AT,
            "source_hierarchy": "PRIMARY_STATEMENT_REPORTED_BY_SECONDARY",
            "independent_group": "primary-statement:rockstar",
            "content_fingerprint": "copied-story",
        },
        {
            "source_name": "Outlet B",
            "title": claim,
            "summary": claim,
            "url": "https://b.example/report",
            "published_at": CHECKED_AT,
            "source_hierarchy": "PRIMARY_STATEMENT_REPORTED_BY_SECONDARY",
            "independent_group": "primary-statement:rockstar",
            "content_fingerprint": "copied-story",
        },
    ]

    result = process_telegram_source_intelligence(
        input_record=record,
        fresh_evidence=_fresh(packet),
    )
    claims = result["claims"]
    assert len(claims) == 1
    assert claims[0]["verification_status"] == "INSUFFICIENT_EVIDENCE"
    assert claims[0]["semantic_memory_id"] is None
    assert result["SEMANTIC_MEMORY_PROMOTED"] == "NO"
    assert result["UNVERIFIED_CLAIM_NOT_PROMOTED"] == "PASS"
    assert result["editorial_signal"]["harness_decision"] == "REJECT_LOW_EVIDENCE"


def test_unresolved_social_source_fails_closed_without_claim_inference():
    url = "https://www.instagram.com/p/example/"
    record = _ingest(url, message_id=9004)
    packet = _base_packet(
        {
            "resolution_status": "FAIL",
            "source_name": "instagram.com",
            "url": url,
            "resolved_url": None,
            "platform": "instagram",
            "retrieved_at": CHECKED_AT,
            "source_hierarchy": None,
            "original_source_retrieved": False,
            "content_excerpt": "",
            "content_sha256": None,
            "independent_group": None,
            "content_fingerprint": None,
            "error": "ValueError",
        }
    )
    result = process_telegram_source_intelligence(
        input_record=record,
        fresh_evidence=_fresh(packet),
    )
    assert result["SOURCE_CONTENT_RESOLVED"] == "FAIL"
    assert result["CLAIMS_EXTRACTED"] == "NO"
    assert result["FACT_CHECK_EXECUTED"] == "NO"
    assert result["UNVERIFIED_CLAIM_NOT_PROMOTED"] == "PASS"
    assert result["editorial_signal"]["harness_decision"] == "REJECT_LOW_EVIDENCE"


def test_gateway_keeps_url_as_source_input_and_hides_telemetry_in_normal_reply():
    assert _conversation_classification_override(
        "confere isso https://example.com/gta"
    ) is None
    reply = _chat_reply_v2(
        {
            "answer": "A fonte foi verificada.",
            "authority": "deepseek_harness",
            "routing_id": "secret-noise",
            "source_intelligence": {
                "editorial_signal": {"harness_decision": "STORE_FOR_FUTURE"}
            },
        }
    )
    assert "A fonte foi verificada." in reply
    assert "Ação: guardar para uso editorial futuro." in reply
    assert "routing_id" not in reply
    assert "secret-noise" not in reply
    assert "Harness evidence" not in reply


def test_reported_primary_statements_share_the_attributed_origin_group():
    first = _secondary_hierarchy(
        {
            "source_name": "Outlet A",
            "title": "According to Rockstar, GTA VI has a new gameplay system",
            "summary": "The outlet reports Rockstar's statement.",
            "url": "https://outlet-a.example/story",
        }
    )
    second = _secondary_hierarchy(
        {
            "source_name": "Outlet B",
            "title": "Rockstar said GTA VI has a new gameplay system",
            "summary": "A separate article repeats the same attributed statement.",
            "url": "https://outlet-b.example/story",
        }
    )
    assert first == (
        "PRIMARY_STATEMENT_REPORTED_BY_SECONDARY",
        "primary-statement:rockstar",
    )
    assert second == first


def test_explicit_video_intent_uses_official_editorial_pipeline_without_production():
    url = "https://www.rockstargames.com/VI/editorial-proof"
    ingested = ingest_telegram_input_under_harness(
        {
            "telegram_user_id": 111,
            "telegram_chat_id": 111,
            "telegram_message_id": 9010,
            "telegram_update_id": 10010,
            "input_kind": "text",
            "text": f"Transforme isso em pauta de vídeo se fizer sentido: {url}",
        }
    )
    record = ingested["input"]
    claim = (
        "Rockstar confirms GTA VI follows Lucia and Jason through Vice City "
        "and the state of Leonida in this official update."
    )
    packet = _base_packet(
        {
            "resolution_status": "PASS",
            "source_name": "Rockstar GTA VI",
            "url": url,
            "resolved_url": url,
            "platform": "web",
            "retrieved_at": CHECKED_AT,
            "source_hierarchy": "OFFICIAL_PRIMARY",
            "original_source_retrieved": True,
            "content_excerpt": claim,
            "content_sha256": "c" * 64,
            "independent_group": "rockstargames.com",
            "content_fingerprint": "official-editorial-proof",
        }
    )
    packet["official_sources"][0]["content_excerpt"] = claim

    result = process_telegram_source_intelligence(
        input_record=record,
        fresh_evidence=_fresh(packet),
    )
    signal = result["editorial_signal"]

    assert signal["status"] == "USED"
    assert signal["harness_decision"] in {
        "USE_FOR_VIDEO",
        "STORE_FOR_FUTURE",
        "REJECT_SATURATED",
    }
    assert signal["payload"]["pipeline_result"] is not None
    assert signal["payload"]["research_item_id"] is not None
    assert signal["payload"]["knowledge_id"] is not None
    assert signal["payload"]["telegram_input_id"] == record["id"]
    assert signal["payload"]["production_dispatched"] is False
    if signal["harness_decision"] == "USE_FOR_VIDEO":
        assert signal["goal_id"]
        assert signal["payload"]["goal_id"] == signal["goal_id"]
