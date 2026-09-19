from types import SimpleNamespace

from app.services import system_synergy_service as synergy
from app.services.youtube_department_service import (
    EXECUTOR_BINDING as YOUTUBE_EXECUTOR,
    execute_youtube_specialist_capability,
    youtube_department_records,
)


def test_tubegent_specialists_are_real_bounded_routing_records():
    records = youtube_department_records()
    assert len(records) == 9
    assert {record.agent_id for record in records} == {
        "tubegent-content-strategy",
        "tubegent-script-review",
        "tubegent-seo",
        "tubegent-thumbnail-strategy",
        "tubegent-production-management",
        "tubegent-publishing-policy",
        "tubegent-analytics",
        "tubegent-monetization",
        "tubegent-optimization",
    }
    assert all(record.executor_binding == YOUTUBE_EXECUTOR for record in records)
    assert all("DeepSeek Harness remains sole authority" in record.security_boundary for record in records)
    assert all("PUBLICATION" not in record.allowed_actions for record in records)


def test_youtube_specialist_requires_evidence_and_returns_to_harness():
    record = next(item for item in youtube_department_records() if item.capability_id == "youtube.department.seo")
    result = execute_youtube_specialist_capability(
        record,
        {
            "objective": "prepare pre-publication metadata",
            "evidence_refs": ["research:e1", "script:s7"],
        },
    )
    assert result["status"] == "EXECUTED"
    assert result["authority"] == synergy.HARNESS_AUTHORITY
    assert result["evidence_refs"] == ("research:e1", "script:s7")
    assert any("DeepSeek Harness" in item for item in result["recommendations"])


def test_ecosystem_registry_contains_existing_and_new_capabilities():
    registry = synergy.ecosystem_registry()
    for capability_id in (
        "agent-office.execute",
        "addy:test-driven-development",
        "gta6.research",
        "script.generate",
        "production.plan",
        "production.media.select-segments",
        "video.edit.vedit",
        "production.render.execute",
        "qa.preflight",
        "telegram.input.ingest",
        "youtube.analytics.read",
        "knowledge.learn.youtube-analytics",
        "youtube.department.seo",
        "youtube.department.thumbnail-strategy",
        "youtube.monetization.observe",
        "system.improvement.propose",
    ):
        record = registry.get(capability_id)
        assert record is not None, capability_id
        assert record.evidence_contract, capability_id

    legacy_render = registry.get("video.render")
    assert legacy_render is not None
    assert legacy_render.available is False
    assert legacy_render.executor_binding is None
    assert legacy_render.implementation.startswith("DEPRECATED SUPPORT PATH:")


def test_harness_routes_every_controlled_stage_and_stops_at_publication_gate():
    proof = synergy.validate_controlled_plan_routing()
    assert proof
    assert proof[-1]["stage"] == "publication_gate"
    assert proof[-1]["status"] == "STOPPED_AT_GATE"
    assert proof[-1]["authority"] == synergy.HARNESS_AUTHORITY
    assert all(item["status"] == "ROUTABLE" for item in proof[:-1])
    assert all(item["authority"] == synergy.HARNESS_AUTHORITY for item in proof)
    assert all(item.get("routing_id") for item in proof[:-1])
    assert all(item.get("executor") for item in proof[:-1])


def test_intelligent_routing_selects_only_requested_specialist():
    decision = synergy.select_specialist(
        intent="youtube seo title description search",
        action="YOUTUBE",
        required_capability_id="youtube.department.seo",
    )
    assert decision.selected_capability_id == "youtube.department.seo"
    assert decision.selected_executor_binding == YOUTUBE_EXECUTOR
    assert decision.policy_metadata["selected_implementation"]["agent_id"] == "tubegent-seo"


def test_capability_matrix_has_operational_contract_fields():
    matrix = synergy.capability_matrix()
    row = next(item for item in matrix if item["capability"] == "youtube.monetization.observe")
    assert row["agent"] == "tubegent-monetization"
    assert row["tool"]
    assert row["prerequisites"]
    assert row["cost"] == "FREE_NO_BILLING"
    assert row["availability"] == "AVAILABLE"
    assert row["authorization_required"] == ("EXECUTION",)
    assert row["input"]
    assert row["output"]
    assert row["evidence"]
    assert row["next_consumer"] == "DeepSeek Harness"


def test_health_report_never_conflates_registered_with_verified():
    report = synergy.build_health_report(now="2026-09-16T23:00:00+00:00")
    entry = next(item for item in report.entries if item.capability_id == "youtube.monetization.observe")
    assert entry.registered is True
    assert entry.available is True
    assert entry.invocable is False
    assert entry.test_result == "NOT_EXERCISED"
    assert entry.degraded_reason
    assert report.authority == synergy.HARNESS_AUTHORITY


def test_system_improvement_is_proposal_only():
    result = synergy.execute_system_improvement_proposal(
        synergy.SYSTEM_IMPROVEMENT_RECORD,
        {"gaps": ["analytics latency high", "thumbnail strategy unverified"]},
    )
    assert result["status"] == "PROPOSAL_ONLY"
    assert result["authority"] == synergy.HARNESS_AUTHORITY
    assert "commit" in result["required_gates"]
    assert "ci" in result["required_gates"]
    assert "explicit_activation" in result["required_gates"]


def test_specialist_binding_fails_closed():
    bad = SimpleNamespace(capability_id="youtube.department.seo", executor_binding="evil")
    try:
        execute_youtube_specialist_capability(bad, {"objective": "x", "evidence_refs": ["e:1"]})
    except PermissionError as exc:
        assert "binding mismatch" in str(exc)
    else:
        raise AssertionError("binding bypass was accepted")
