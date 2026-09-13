from __future__ import annotations

from dataclasses import replace
import json

import pytest

from app.integrations.deepseek_harness import server
from app.services.codex_addy_capability_executor import _payload_prompt
from app.services.global_capability_registry import (
    ADDY_SKILLS,
    AVAILABLE,
    BLOCKED,
    GLOBAL_CAPABILITY_REGISTRY,
    UNKNOWN,
)
from app.services.gta6_action_dispatcher import GTA6ActionDispatcher
from app.services.gta6_brain import BrainDecision
from app.services.gta6_master_agent import GTA6MasterAgent
from app.services.harness_authorization_service import (
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_capability_service import execute_capability
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    RoutingPolicyError,
    route_harness_request,
)


def _addy_route(skill: str = "code-review-and-quality"):
    return route_harness_request(
        HarnessRoutingRequest(
            intent=skill.replace("-", " "),
            authorized_action="DEVELOPMENT",
            required_capability_id=f"addy:{skill}",
            domain="development",
            fallback_allowed=False,
        )
    )


def _capability_auth(capability_id: str, action: str, *, execution_id: str = "gate4-exec"):
    return issue_harness_authorization(
        authorized_action=action,
        subject=f"capability:{capability_id}",
        harness_decision_id="gate4-decision",
        execution_id=execution_id,
        lineage={"gate": 4},
    )


def test_harness_routing_selects_exactly_one_addy_skill_with_explainable_metadata():
    decision = _addy_route()
    selected = decision.policy_metadata["selected_implementation"]
    assert decision.selected_capability_id == "addy:code-review-and-quality"
    assert selected["type"] == "SKILL"
    assert selected["agent_id"] == "codex"
    assert selected["skill_id"] == "code-review-and-quality"
    assert selected["executor_binding"] == decision.selected_executor_binding
    assert selected["evidence_contract"].endswith("CapabilityEvidence")
    assert decision.fallback_occurred is False
    assert any("selected by Harness policy" in reason for reason in decision.rationale)


def test_registry_remains_metadata_only_and_never_authorizes_or_executes():
    registry = GLOBAL_CAPABILITY_REGISTRY
    assert not hasattr(registry, "authorize")
    assert not hasattr(registry, "execute")
    metadata = registry.get("addy:code-review-and-quality").metadata()
    assert "authorization_id" not in metadata
    assert "prompt" not in metadata


def test_addy_inventory_is_pinned_bounded_and_individually_selectable():
    records = [r for r in GLOBAL_CAPABILITY_REGISTRY.all() if r.capability_id.startswith("addy:")]
    assert len(ADDY_SKILLS) == 24
    assert len(records) == len(ADDY_SKILLS)
    assert len({r.skill_id for r in records}) == 24
    assert all(r.allowed_actions == ("DEVELOPMENT",) for r in records)
    assert all(r.agent_id == "codex" for r in records)
    assert all("one selected skill only" in r.security_boundary for r in records)
    assert all(r.executor_binding.endswith("execute_codex_addy_capability") for r in records)


def test_selected_addy_prompt_names_only_selected_skill_and_forbids_other_skills():
    prompt = _payload_prompt(
        skill_name="code-review-and-quality",
        payload={"task": "Review the changed Python files."},
    )
    assert "@code-review-and-quality" in prompt
    assert "invoke other skills" in prompt
    assert "@test-driven-development" not in prompt


def test_harness_boundary_routes_before_issuing_authorization(monkeypatch):
    calls = []
    real_route = server.route_harness_request
    real_issue = server.issue_harness_authorization

    def routed(request):
        calls.append("route")
        return real_route(request)

    def issued(**kwargs):
        calls.append("authorize")
        return real_issue(**kwargs)

    monkeypatch.setattr(server, "route_harness_request", routed)
    monkeypatch.setattr(server, "issue_harness_authorization", issued)
    monkeypatch.setattr(
        server,
        "execute_codex_addy_capability",
        lambda capability, payload: {"skill": capability.capability_id, "ok": True},
    )

    result = json.loads(
        server.br_capability_execute(
            capability_id="addy:code-review-and-quality",
            authorized_action="DEVELOPMENT",
            payload_json='{"task":"review"}',
        )
    )["result"]
    assert calls[:2] == ["route", "authorize"]
    assert result["status"] == "EXECUTED"
    assert result["authorization_id"]
    assert result["harness_routing"]["selected_implementation"]["skill_id"] == "code-review-and-quality"
    assert result["harness_routing"]["fallback_occurred"] is False


def test_fabricated_authorization_is_rejected_even_with_valid_route():
    with pytest.raises(PermissionError, match="not found"):
        execute_capability(
            capability_id="addy:code-review-and-quality",
            authorization="fabricated",
            payload={},
            routing_decision=_addy_route(),
        )


def test_missing_authorization_fails_closed_even_with_valid_route():
    with pytest.raises(PermissionError, match="authorization_id"):
        execute_capability(
            capability_id="addy:code-review-and-quality",
            authorization=None,  # type: ignore[arg-type]
            payload={},
            routing_decision=_addy_route(),
        )


def test_wrong_action_fails_closed():
    auth = _capability_auth("addy:code-review-and-quality", "EDITORIAL")
    with pytest.raises(PermissionError, match="not authorized"):
        execute_capability(
            capability_id="addy:code-review-and-quality",
            authorization=auth,
            payload={},
            routing_decision=_addy_route(),
        )


def test_wrong_execution_id_fails_closed_at_existing_authorization_boundary():
    auth = _capability_auth("addy:code-review-and-quality", "DEVELOPMENT", execution_id="actual")
    with pytest.raises(PermissionError, match="execution_id mismatch"):
        validate_harness_authorization(
            auth,
            expected_action="DEVELOPMENT",
            expected_subject="capability:addy:code-review-and-quality",
            expected_execution_id="different",
        )


def test_routing_decision_cannot_be_reused_for_another_skill():
    auth = _capability_auth("addy:test-driven-development", "DEVELOPMENT")
    with pytest.raises(PermissionError, match="routing capability mismatch"):
        execute_capability(
            capability_id="addy:test-driven-development",
            authorization=auth,
            payload={},
            routing_decision=_addy_route("code-review-and-quality"),
        )


def test_blocked_higgsfield_is_rejected_before_authorization_or_executor(monkeypatch):
    issued = False

    def unexpected_issue(**kwargs):
        nonlocal issued
        issued = True
        raise AssertionError("authorization must not be issued")

    monkeypatch.setattr(server, "issue_harness_authorization", unexpected_issue)
    result = json.loads(
        server.br_capability_execute(
            capability_id="higgsfield-generate",
            authorized_action="EXECUTION",
            payload_json='{"prompt":"x"}',
        )
    )["result"]
    assert result["status"] == "BLOCKED"
    assert result["active"] is False
    assert result["authorization_id"] is None
    assert result["result"]["stage"] == "routing"
    assert issued is False


def test_unknown_tubegent_is_not_selected_or_invented():
    record = GLOBAL_CAPABILITY_REGISTRY.get("tubegent")
    assert record is not None
    assert record.availability == UNKNOWN
    assert record.executor_binding is None
    with pytest.raises(RoutingPolicyError, match="No executable capability"):
        route_harness_request(
            HarnessRoutingRequest(
                intent="tubegent agent",
                authorized_action="DEVELOPMENT",
                required_capability_id="tubegent",
            )
        )


def test_native_gta6_skill_mappings_are_explicit_and_fact_check_stays_unproven():
    expected = {
        "gta6.research": ("gta6-research", "RESEARCH"),
        "editorial.process": ("gta6-editorial", "EDITORIAL"),
        "production.plan": ("gta6-production", "EXECUTION"),
        "youtube.upload-private": ("gta6-youtube", "YOUTUBE"),
        "youtube.publish-public": ("gta6-youtube", "PUBLICATION"),
    }
    for capability_id, (skill_id, action) in expected.items():
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        assert record.skill_id == skill_id
        assert action in record.allowed_actions
        assert record.executor_binding
        assert record.evidence_contract
    fact_check = GLOBAL_CAPABILITY_REGISTRY.get("gta6.fact-check")
    assert fact_check.skill_id == "gta6-fact-check"
    assert fact_check.availability == UNKNOWN
    assert fact_check.executor_binding is None


def test_youtube_skill_keeps_private_upload_and_publication_authorization_distinct():
    upload = GLOBAL_CAPABILITY_REGISTRY.get("youtube.upload-private")
    publish = GLOBAL_CAPABILITY_REGISTRY.get("youtube.publish-public")
    assert upload.skill_id == publish.skill_id == "gta6-youtube"
    assert upload.allowed_actions == ("YOUTUBE",)
    assert publish.allowed_actions == ("PUBLICATION",)
    assert "PUBLICATION authorization" in publish.security_boundary


def test_render_keeps_execution_authorization_boundary():
    render = GLOBAL_CAPABILITY_REGISTRY.get("video.render")
    assert render.allowed_actions == ("EXECUTION",)
    assert "fail-closed render boundary" in render.security_boundary


def test_addy_skill_never_selects_provider_or_model_sovereignly():
    decision = _addy_route()
    assert decision.selected_provider is None
    assert decision.selected_model is None
    selected = decision.policy_metadata["selected_implementation"]
    assert selected["skill_id"] == "code-review-and-quality"


def test_no_eligible_implementation_fails_closed_without_fallback():
    with pytest.raises(RoutingPolicyError, match="No executable capability") as exc_info:
        route_harness_request(
            HarnessRoutingRequest(
                intent="gta6 fact check",
                authorized_action="EDITORIAL",
                required_capability_id="gta6.fact-check",
                fallback_allowed=False,
            )
        )
    assert exc_info.value.evidence["authorized_action"] == "EDITORIAL"


def test_master_agent_remains_subordinate_to_harness_routed_provider():
    with pytest.raises(PermissionError, match="Harness-routed AI provider"):
        GTA6MasterAgent()


def test_dispatcher_does_not_fabricate_authorization():
    dispatcher = GTA6ActionDispatcher(
        monitor=lambda **kwargs: None,
        research=lambda: None,
        editorial=lambda context: None,
        execution=lambda context: None,
        youtube=lambda: None,
    )
    with pytest.raises(PermissionError, match="Harness authorization is required"):
        dispatcher.dispatch(BrainDecision(action="RESEARCH", reason="x", priority="LOW", confidence=1.0))


def test_routing_metadata_never_injects_skill_body():
    decision = _addy_route()
    metadata = decision.policy_metadata["selected_implementation"]
    assert set(metadata) == {
        "type",
        "implementation",
        "agent_id",
        "skill_id",
        "executor_binding",
        "evidence_contract",
        "side_effects",
        "instruction_path",
    }
    assert metadata["instruction_path"].endswith("/code-review-and-quality/SKILL.md")
    assert "Use only @" not in json.dumps(decision.to_dict())


def test_explicit_policy_fallback_remains_observable_and_agent_skill_has_none():
    decision = _addy_route()
    assert decision.fallback_allowed is False
    assert decision.fallback_candidates == ()
    assert decision.fallback_occurred is False
