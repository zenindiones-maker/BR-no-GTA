from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.database.telegram_brand_asset_repository import (
    get_active_brand_asset,
    list_active_brand_assets,
)
from app.services.global_capability_registry import (
    AVAILABLE,
    FUNCTIONAL,
    GLOBAL_CAPABILITY_REGISTRY,
)
from app.services.harness_authorization_service import (
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.telegram_harness_service import (
    TELEGRAM_ASSET_CAPABILITY_ID,
    TELEGRAM_ASSET_EXECUTOR_BINDING,
    _telegram_semantic_routing_request,
    build_harness_connection_proof,
    chat_under_harness,
    execute_telegram_asset_registration_capability,
    register_telegram_brand_asset_under_harness,
)
from scripts.telegram_harness_gateway import (
    _classify_brand_asset,
    _extract_attachment,
)


@pytest.fixture(autouse=True)
def _materialize_existing_nvidia_runtime_contract(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "fixture-key")
    monkeypatch.setenv(
        "BR_NVIDIA_HEALTH_MAX_AGE_SECONDS",
        "315360000",
    )
    monkeypatch.delenv(
        "BR_RUNTIME_MODEL_HEALTH_JSON",
        raising=False,
    )


def _asset_payload(*, message_id: int = 10, file_id: str = "file-A", unique_id: str = "unique-A"):
    return {
        "asset_type": "watermark",
        "telegram_file_id": file_id,
        "telegram_file_unique_id": unique_id,
        "media_kind": "photo",
        "file_name": None,
        "mime_type": "image/jpeg",
        "file_size": 12345,
        "width": 512,
        "height": 512,
        "duration_seconds": None,
        "telegram_user_id": 111,
        "telegram_chat_id": 111,
        "telegram_message_id": message_id,
        "telegram_update_id": message_id + 100,
        "caption": "essa é a marca d'água oficial",
        "remote_verified": True,
    }


def test_registry_contains_exact_telegram_asset_capability():
    record = GLOBAL_CAPABILITY_REGISTRY.get(TELEGRAM_ASSET_CAPABILITY_ID)
    assert record is not None
    assert record.availability == AVAILABLE
    assert record.maturity == FUNCTIONAL
    assert record.allowed_actions == ("EXECUTION",)
    assert record.domain == "telegram-ingress"
    assert record.executor_binding == TELEGRAM_ASSET_EXECUTOR_BINDING
    assert record.fallback_eligibility is False
    assert "publication authority" in record.security_boundary


def test_telegram_asset_routes_through_harness_and_persists_only_verified_identity():
    result = register_telegram_brand_asset_under_harness(_asset_payload())

    assert result["status"] == "REGISTERED"
    assert result["authority"] == "deepseek_harness"
    assert result["capability_id"] == TELEGRAM_ASSET_CAPABILITY_ID
    assert result["asset"]["asset_type"] == "watermark"
    assert result["asset"]["remote_verified"] is True
    assert result["asset"]["telegram_file_unique_id"] == "unique-A"
    assert "telegram_file_id" not in result["asset"]

    stored = get_active_brand_asset("watermark")
    assert stored is not None
    assert stored["telegram_file_id"] == "file-A"
    assert stored["provenance"]["source"] == "telegram"
    assert stored["provenance"]["authorization_id"] == result["authorization_id"]


def test_new_brand_asset_replaces_active_asset_without_deleting_provenance():
    first = register_telegram_brand_asset_under_harness(
        _asset_payload(message_id=10, file_id="file-A", unique_id="unique-A")
    )
    second_payload = _asset_payload(message_id=11, file_id="file-B", unique_id="unique-B")
    second_payload["asset_type"] = "watermark"
    second = register_telegram_brand_asset_under_harness(second_payload)

    active = get_active_brand_asset("watermark")
    assert active is not None
    assert active["id"] == second["asset"]["id"]
    assert active["telegram_file_unique_id"] == "unique-B"
    records = list_active_brand_assets()
    assert [item["id"] for item in records if item["asset_type"] == "watermark"] == [
        second["asset"]["id"]
    ]
    assert first["asset"]["id"] != second["asset"]["id"]


def test_asset_registration_fails_closed_when_remote_identity_was_not_verified():
    payload = _asset_payload()
    payload["remote_verified"] = False
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="register verified Telegram branding asset intro watermark provenance",
            authorized_action="EXECUTION",
            domain="telegram-ingress",
            required_capability_id=TELEGRAM_ASSET_CAPABILITY_ID,
            required_policy_tags=("telegram", "asset", "branding"),
            fallback_allowed=False,
            zero_cost_operation=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{TELEGRAM_ASSET_CAPABILITY_ID}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
        },
    )

    with pytest.raises(ValueError, match="verified"):
        execute_telegram_asset_registration_capability(
            payload=payload,
            authorization=authorization,
            routing_decision=routing,
        )

    assert get_active_brand_asset("watermark") is None


def test_gateway_recognizes_intro_and_watermark_natural_language_and_extracts_real_telegram_ids():
    assert _classify_brand_asset("essa é a intro oficial do canal", None) == "intro"
    assert _classify_brand_asset("minha marca d'água final", None) == "watermark"
    assert _classify_brand_asset("arquivo novo", "BRNO_GTA_intro_final.mp4") == "intro"
    assert _classify_brand_asset("arquivo novo", "logo.png") is None

    attachment = _extract_attachment(
        {
            "video": {
                "file_id": "telegram-file-id",
                "file_unique_id": "telegram-unique-id",
                "file_name": "intro.mp4",
                "mime_type": "video/mp4",
                "file_size": 999,
                "width": 1920,
                "height": 1080,
                "duration": 5,
            }
        }
    )
    assert attachment == {
        "media_kind": "video",
        "telegram_file_id": "telegram-file-id",
        "telegram_file_unique_id": "telegram-unique-id",
        "file_name": "intro.mp4",
        "mime_type": "video/mp4",
        "file_size": 999,
        "width": 1920,
        "height": 1080,
        "duration_seconds": 5,
    }


def test_harness_connection_proof_contains_persisted_route_and_authority():
    proof = build_harness_connection_proof()

    assert proof["TELEGRAM_HARNESS"] == "PASS"
    assert proof["authority"] == "deepseek_harness"
    assert proof["authorization_status"] == "consumed"
    assert proof["selected_capability_id"] == "ai.reasoning.text"
    assert proof["selected_provider"]
    assert proof["selected_model"]
    assert proof["provider_executor"]
    assert proof["primary_provider"] == proof["selected_provider"]
    assert proof["fallback_occurred"] is False
    assert proof["zero_cost_operation"] is True
    assert proof["routing_id"]
    assert proof["authorization_id"]


def test_normal_chat_uses_harness_selected_provider_and_returns_provenance(monkeypatch):
    captured = {}

    def fake_execute(*, prompt, authorization, routing_decision):
        assert "MENSAGEM_USUARIO=Qual é o estado do canal?" in prompt
        captured["provider"] = routing_decision.selected_provider
        captured["model"] = routing_decision.selected_model
        captured["fallback_allowed"] = routing_decision.fallback_allowed
        return SimpleNamespace(
            provider=routing_decision.selected_provider,
            status="EXECUTED",
            active=True,
            authority="deepseek_harness",
            authorized_action="DECISION",
            execution_id=authorization.execution_id,
            result={
                "text": "Estado consultado sob autoridade do Harness.",
                "model": routing_decision.selected_model,
            },
        )

    monkeypatch.setattr(
        "app.services.telegram_harness_service.execute_harness_ai_generation",
        fake_execute,
    )

    result = chat_under_harness("Qual é o estado do canal?")

    assert result["answer"] == "Estado consultado sob autoridade do Harness."
    assert result["authority"] == "deepseek_harness"
    assert result["authorized_action"] == "DECISION"
    assert result["capability_id"] == "ai.reasoning.text"
    assert result["provider"] == captured["provider"]
    assert result["model"] == captured["model"]
    assert captured["provider"]
    assert captured["model"]
    assert captured["fallback_allowed"] is False
    assert result["fallback_occurred"] is False
    assert result["zero_cost_operation"] is True
    assert result["routing_id"]
    assert result["authorization_id"]


def test_telegram_generic_semantic_routing_is_provider_agnostic_and_fail_closed():
    request = _telegram_semantic_routing_request(
        intent="answer generic Telegram message",
        task_class="telegram-reasoning",
        goal_id="telegram:test:provider-governance",
        learning_required=True,
    )
    assert request.required_capability_id == "ai.reasoning.text"
    assert request.provider_required is True
    assert request.preferred_providers == ()
    assert request.allowed_providers == ()
    assert request.preferred_models == ()
    assert request.fallback_allowed is False
    assert request.zero_cost_operation is True
