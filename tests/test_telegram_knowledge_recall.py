from __future__ import annotations

from app.database import continuous_operation_repository as continuous_repository
from app.database.memory_claim_repository import insert_memory_claim
from app.services.memory_claim_service import create_memory_claim
from app.services.telegram_conversation_service import (
    classify_conversation_intent,
    handle_telegram_conversation,
    plan_natural_language_action,
)
from app.services.telegram_knowledge_recall_service import recall_canonical_gta6_knowledge


def _presenter(canonical, **_kwargs):
    return {"text": canonical.get("answer", "")}


def _insert_jason_claim():
    claim = create_memory_claim(
        claim=(
            "Jason Duval grew up around grifters and crooks, spent time in the Army, "
            "and found himself in the Keys doing what he knows best for local drug runners."
        ),
        claim_type="fact",
        confidence=10.0,
        status="active",
        scope="gta6",
        extraction_method="rockstar-official-source",
    )
    claim_id = insert_memory_claim(claim)
    continuous_repository.upsert_claim_lineage({
        "claim_id": claim_id,
        "subject": "Jason Duval",
        "source_id": "rockstar-only-in-leonida",
        "source_url": "https://www.rockstargames.com/VI/only-in-leonida",
        "source_type": "PRIMARY_SOURCE",
        "published_at": None,
        "observed_at": "2026-09-21T12:00:00+00:00",
        "evidence_ref": "rockstar:only-in-leonida:jason-duval",
        "evidence_class": "PRIMARY_SOURCE",
        "status_snapshot": "active",
        "supersedes_claim_id": None,
        "related_claims": [],
        "metadata": {"authority": "Rockstar Games"},
    })
    return claim_id


def test_screenshot_phrase_routes_to_provider_free_knowledge_recall():
    text = "Conhecimento sobre o gta 6"
    intent = classify_conversation_intent(text)
    assert intent == "KNOWLEDGE_RECALL_REQUEST"
    plan = plan_natural_language_action(
        text,
        intent=intent,
        state={"active_project": "BR-no-GTA"},
        resolved_reference=None,
    )
    assert plan["kind"] == "KNOWLEDGE_RECALL"
    assert plan["authorized_action"] == "DECISION"


def test_gta6_knowledge_recall_uses_canonical_claim_and_provenance_without_provider():
    claim_id = _insert_jason_claim()
    calls = {"provider": 0, "action": 0}
    progress = []

    def provider(*_args, **_kwargs):
        calls["provider"] += 1
        raise AssertionError("knowledge recall must not call ai.reasoning.text")

    def action(*_args, **_kwargs):
        calls["action"] += 1
        raise AssertionError("knowledge recall must not dispatch execution")

    result = handle_telegram_conversation(
        "Conhecimento sobre o gta 6",
        telegram_chat_id=881001,
        telegram_message_id=881002,
        chat_handler=provider,
        action_executor=action,
        progress_callback=lambda stage, message: progress.append((stage, message)),
        presenter=_presenter,
    )

    canonical = result["canonical_result"]
    assert result["intent"] == "KNOWLEDGE_RECALL_REQUEST"
    assert result["plan"]["kind"] == "KNOWLEDGE_RECALL"
    assert canonical["status"] == "CANONICAL_KNOWLEDGE_RECALLED"
    assert canonical["provider_independent"] is True
    assert canonical["provider_calls"] == 0
    assert canonical["semantic_provider_required"] is False
    assert canonical["canonical_memory_plane"] == "BR_SQLITE"
    assert canonical["obsidian_role"] == "PUBLISHED_MEMORY_VIEW"
    assert canonical["SOURCE_PROVENANCE_PRESERVED"] == "PASS"
    assert claim_id in {item["claim_id"] for item in canonical["claims"]}
    assert "Jason Duval" in result["answer"]
    assert "rockstargames.com/VI/only-in-leonida" in result["answer"]
    assert "SEMANTIC_REASONING_PROVIDER_UNAVAILABLE" not in result["answer"]
    assert calls == {"provider": 0, "action": 0}
    assert progress == []


def test_specific_canonical_knowledge_recall_is_lexical_and_provider_free():
    claim_id = _insert_jason_claim()
    recalled = recall_canonical_gta6_knowledge(
        "Conhecimento sobre Jason Duval"
    )
    assert recalled["status"] == "CANONICAL_KNOWLEDGE_RECALLED"
    assert recalled["provider_calls"] == 0
    assert recalled["provider_independent"] is True
    assert claim_id in {item["claim_id"] for item in recalled["claims"]}
    assert recalled["claims"][0]["source_type"] == "PRIMARY_SOURCE"


def test_out_of_scope_knowledge_recall_fails_as_memory_miss_not_provider_failure():
    calls = {"provider": 0}
    result = handle_telegram_conversation(
        "Conhecimento sobre gta 7",
        telegram_chat_id=881011,
        telegram_message_id=881012,
        chat_handler=lambda *_a, **_k: calls.__setitem__("provider", calls["provider"] + 1),
        presenter=_presenter,
    )
    canonical = result["canonical_result"]
    assert result["intent"] == "KNOWLEDGE_RECALL_REQUEST"
    assert canonical["status"] == "NO_CANONICAL_KNOWLEDGE_MATCH"
    assert canonical["provider_independent"] is True
    assert canonical["provider_calls"] == 0
    assert calls["provider"] == 0
    assert "não há conhecimento canônico suficiente" in result["answer"].casefold()
