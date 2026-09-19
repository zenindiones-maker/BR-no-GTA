from __future__ import annotations

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY, UNKNOWN
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_mcp_capability_execution import execute_mcp_capability
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request


def _forbidden_skill_executor(*args, **kwargs):
    raise AssertionError("native capability escaped into generic skill executor")


def test_native_media_discovery_executes_through_harness_boundary():
    capability_id = "media.discovery"
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="discover GTA VI media candidates from bounded search results",
            authorized_action="EXECUTION",
            required_capability_id=capability_id,
            domain="media",
            fallback_allowed=False,
            provider_required=False,
            learning_required=False,
        )
    )
    implementation = dict(routing.policy_metadata["selected_implementation"])
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{capability_id}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
        },
    )
    try:
        evidence = execute_mcp_capability(
            routing_decision=routing,
            authorization=authorization,
            payload={
                "topic": "Vice City",
                "results": [
                    {
                        "title": "Grand Theft Auto VI Trailer 2",
                        "url": "https://www.youtube.com/watch?v=example",
                        "source": "youtube",
                        "description": "GTA VI Vice City Lucia Jason",
                        "source_authority": "official",
                    }
                ],
            },
            implementation=implementation,
            skill_executor=_forbidden_skill_executor,
        )
    finally:
        consume_harness_authorization(authorization)
    assert evidence.status == "EXECUTED"
    assert evidence.active is True
    assert evidence.result["status"] == "EXECUTED"
    assert evidence.result["candidate_count"] == 1


def test_legacy_duplicate_paths_are_not_directly_routable():
    for capability_id in (
        "cloud.github-actions",
        "media.ffmpeg",
        "media.select",
        "media.technical-analysis",
        "video.render",
    ):
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        assert record is not None
        assert record.availability == UNKNOWN
        assert record.executor_binding is None
        assert record.implementation.startswith("DEPRECATED SUPPORT PATH:")


def test_safe_native_records_use_exact_callable_bindings():
    expected = {
        "media.discovery": "app.services.native_capability_adapters.execute_media_discovery_capability",
        "production.plan": "app.services.native_capability_adapters.execute_production_plan_capability",
        "qa.preflight": "app.services.native_capability_adapters.execute_qa_preflight_capability",
        "script.generate": "app.services.native_capability_adapters.execute_script_generate_capability",
        "video.edit.vedit": "app.services.native_capability_adapters.execute_vedit_plan_capability",
        "media.analysis.cloud": "app.services.media_analysis_cloud_service.execute_media_analysis_cloud_capability",
        "gta6.brain.decide": "app.services.gta6_brain_harness_service.execute_authorized_gta6_brain_decision",
    }
    for capability_id, binding in expected.items():
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        assert record is not None
        assert record.available is True
        assert record.executor_binding == binding
