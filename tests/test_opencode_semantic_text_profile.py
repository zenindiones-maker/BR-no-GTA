from types import SimpleNamespace

import json
import pytest

from app.services.harness_ai_provider_service import HarnessAIProviderEvidence
from app.services.opencode_executor_profile_service import (
    CANDIDATE_OPENCODE_EXECUTOR_VERSION,
    SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION,
    OpenCodeDisprovenSemanticProfileError,
    _DisprovenSemanticProvider,
    executable_opencode_executor_profile,
)
from app.services.opencode_native_ai_provider import (
    _same_runner_cli_command,
    build_semantic_text_only_env,
)
from app.services.opencode_semantic_profile import (
    OPENCODE_SEMANTIC_AGENT_ID,
    OPENCODE_SEMANTIC_CONTRACT,
    OPENCODE_SEMANTIC_PROFILE_VERSION,
    semantic_text_only_config,
)
from app.services.telegram_harness_service import _attempt_governed_reasoning_fallback
from app.services.telegram_reasoning_learning_service import (
    _failure_metadata,
    _failure_pattern,
)


def _failed_opencode_evidence() -> HarnessAIProviderEvidence:
    return HarnessAIProviderEvidence(
        provider="opencode",
        status="FAILED",
        active=False,
        authority="deepseek_harness",
        authorized_action="DECISION",
        harness_decision_id="decision-semantic",
        execution_id="execution-semantic",
        authorization_id="authorization-semantic",
        error={
            "provider": "opencode",
            "model": "oc/big-pickle",
            "code": "semantic_tools_used",
            "tool_call_count": 6,
            "semantic_agent": "build",
            "profile_version": "v2",
        },
        model="oc/big-pickle",
        executor_binding=(
            "app.services.opencode_executor_profile_service."
            "create_opencode_provider_for_active_profile"
        ),
        provider_profile_skill_id="ai.reasoning.opencode-executor-profile",
        provider_profile_version="v2",
        provider_profile_content_ref="profile:v2",
        provider_profile_checksum="checksum-v2",
    )





def test_keyless_opencode_console_uses_official_shared_client_not_standalone():
    command, mode = _same_runner_cli_command(
        executor_model="opencode/big-pickle",
        prompt="Responda apenas: TESTE_OK",
    )
    assert command[:2] == ["opencode", "run"]
    assert "--standalone" not in command
    assert mode == "shared_client"
    assert command[command.index("--agent") + 1] == "build"
    assert command[command.index("--format") + 1] == "json"


def test_external_provider_keeps_documented_standalone_ci_mode():
    command, mode = _same_runner_cli_command(
        executor_model="anthropic/claude-sonnet-4-5",
        prompt="Responda apenas: TESTE_OK",
    )
    assert command[:3] == ["opencode", "run", "--standalone"]
    assert mode == "standalone"

def test_semantic_v3_preserves_builtin_build_and_uses_global_deny_all():
    config = semantic_text_only_config()
    assert config["default_agent"] == OPENCODE_SEMANTIC_AGENT_ID
    assert "agents" not in config
    assert config["permissions"] == [
        {"action": "*", "resource": "*", "effect": "deny"}
    ]


def test_semantic_inline_config_is_actually_injected_into_process_env():
    env = build_semantic_text_only_env({"PATH": "/bin"})
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert env["PATH"] == "/bin"
    assert config["default_agent"] == "build"
    assert "agents" not in config
    assert config["permissions"] == [
        {"action": "*", "resource": "*", "effect": "deny"}
    ]


def test_v2_profile_is_fail_closed_after_confirmed_tool_use():
    profile = executable_opencode_executor_profile(
        CANDIDATE_OPENCODE_EXECUTOR_VERSION
    )
    provider = _DisprovenSemanticProvider(profile)
    with pytest.raises(OpenCodeDisprovenSemanticProfileError) as exc_info:
        provider.generate("Onde estamos?")
    payload = exc_info.value.to_dict()
    assert payload["code"] == "semantic_tools_used"
    assert payload["observed_failure_run_id"] == 35537494044
    assert payload["observed_failure_artifact_id"] == 10612603412
    assert payload["profile_version"] == "v2"


def test_v3_profile_is_a_distinct_candidate_identity():
    profile = executable_opencode_executor_profile(
        SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION
    )
    options = profile["options"]
    assert profile["version"] == "v3"
    assert options["semantic_profile"] == OPENCODE_SEMANTIC_PROFILE_VERSION
    assert options["semantic_agent"] == OPENCODE_SEMANTIC_AGENT_ID
    assert options["semantic_steps"] is None
    assert options["semantic_contract"] == OPENCODE_SEMANTIC_CONTRACT
    assert options["status"] == "CANDIDATE_ROOT_CAUSE_FIX"


def test_learning_persists_exact_confirmed_failure_pattern_and_scope():
    evidence = _failed_opencode_evidence()
    assert _failure_pattern(evidence) == "opencode_semantic_tools_used"
    metadata = _failure_metadata(
        evidence,
        input_record={
            "id": 1,
            "telegram_chat_id": 2,
            "telegram_message_id": 3,
        },
    )
    assert metadata["failure_class"] == "opencode_semantic_tools_used"
    assert metadata["affected_task_class"] == "telegram.reasoning"
    assert metadata["provider"] == "opencode"
    assert metadata["model"] == "oc/big-pickle"
    assert metadata["provider_profile_version"] == "v2"
    assert metadata["diagnostic_status"] == "ROOT_CAUSE_CONFIRMED"


def test_governed_fallback_fails_closed_when_no_zero_cost_candidate_is_eligible():
    primary_routing = SimpleNamespace(
        selected_provider="opencode",
        selected_model="oc/big-pickle",
    )
    fallback_evidence, fallback_routing, learned, audit = (
        _attempt_governed_reasoning_fallback(
            prompt="Onde estamos?",
            primary_routing=primary_routing,
            primary_evidence=_failed_opencode_evidence(),
            telegram_goal="telegram:2:3",
            telegram_lineage={
                "telegram_input_id": 1,
                "telegram_chat_id": 2,
                "telegram_message_id": 3,
            },
            progress_callback=None,
            input_record=None,
        )
    )
    assert fallback_evidence is None
    assert fallback_routing is None
    assert learned is None
    assert audit["PRIMARY_PROVIDER"] == "opencode"
    assert audit["PRIMARY_FAILURE"] == "semantic_tools_used"
    assert audit["FALLBACK_OCCURRED"] == "NO"
    assert audit["FALLBACK_REASON"] == "no_policy_eligible_provider"
