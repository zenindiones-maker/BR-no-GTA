from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.services.editorial_queue_consumer import (
    process_next_editorial_queue_item,
)
from app.services.gta6_master_agent import GTA6MasterAgent
from app.services.global_capability_registry import BLOCKED, UNKNOWN
from app.services.codex_addy_capability_executor import (
    execute_codex_addy_capability,
)
from app.services.harness_ai_provider_service import (
    select_harness_ai_provider,
)
from app.services.harness_capability_service import discover_capabilities
from app.services.harness_mcp_capability_execution import execute_mcp_capability
from app.services.harness_authorization_service import (
    HARNESS_ISSUER,
    authorization_to_context,
    issue_harness_authorization,
)
from app.services.harness_execution_result import (
    CanonicalExecutionResult,
    canonical_execution_result,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    RoutingPolicyError,
    route_harness_request,
)
from app.services.google_youtube_publication_service import (
    process_next_youtube_publication,
    reconcile_youtube_publication_visibility_with_google,
)
from app.services.harness_youtube_publication_service import (
    publish_targeted_publication,
)
from app.services.youtube_cloud_upload_service import (
    dispatch_targeted_private_upload,
    reconcile_targeted_private_upload,
)
from app.services.youtube_publication_readiness_service import (
    build_youtube_publication_preview,
)
from app.services.gta6_observation_service import build_gta6_observation
from app.services.gta6_knowledge_query_service import (
    knowledge_context_to_dict,
    query_gta6_knowledge_context,
)
from app.services.gta6_research_pipeline import run_gta6_research
from app.services.production_execution_service import (
    process_next_production_execution,
)
from app.main import initialize_application


mcp = FastMCP(
    "BR-no-GTA",
)


def _json_result(
    *,
    operation: str,
    result: Any,
    evidence: CanonicalExecutionResult | None = None,
) -> str:
    """Serialize a BR operation result for MCP with optional canonical evidence."""
    serialized_result = (
        asdict(result)
        if is_dataclass(result)
        else result
    )
    payload = {
        "operation": operation,
        "result": serialized_result,
    }
    if evidence is not None:
        payload["evidence"] = evidence.to_dict()

    return json.dumps(
        payload,
        ensure_ascii=False,
        default=str,
    )


def _normalize_optional_goal_id(goal_id: str | None) -> str | None:
    if goal_id is None:
        return None
    if not isinstance(goal_id, str) or not goal_id.strip():
        raise ValueError("goal_id must be a non-empty string or None")
    return goal_id.strip()


def _normalize_optional_target_duration_seconds(
    target_duration_seconds: float | None,
) -> float | None:
    if target_duration_seconds is None:
        return None
    if isinstance(target_duration_seconds, bool) or not isinstance(
        target_duration_seconds, (int, float)
    ):
        raise ValueError("target_duration_seconds must be numeric or None")
    value = float(target_duration_seconds)
    if value <= 0 or value > 7200:
        raise ValueError("target_duration_seconds must be in (0, 7200]")
    return value


@mcp.tool()
def br_observe() -> str:
    """
    Observe the current GTA6 operational state.

    This is a read-only observation tool for the DeepSeek Harness.
    It does not execute pipelines, call AI, or modify persistence.
    """
    result = build_gta6_observation()
    return _json_result(
        operation="br_observe",
        result=result,
    )


@mcp.tool()
def br_knowledge_query(query: str) -> str:
    """
    Query the GTA6 Knowledge Brain.

    Returns the most relevant persisted knowledge context,
    including confidence and evidence lineage.
    """
    context = query_gta6_knowledge_context(
        query=query,
    )

    if context is None:
        result = {
            "status": "no_knowledge",
            "query": query,
            "reason": "Nenhum conhecimento relevante encontrado no GTA6 Knowledge Brain.",
        }
    else:
        result = knowledge_context_to_dict(context)

    return _json_result(
        operation="br_knowledge_query",
        result=result,
    )


@mcp.tool()
def br_research_run() -> str:
    """Execute the official GTA6 research pipeline under Harness authority."""
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="execute official GTA6 research pipeline",
            authorized_action="RESEARCH",
            fallback_allowed=False,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="RESEARCH",
        subject="action:RESEARCH",
        lineage={
            "routing_id": routing.routing_id,
            "selected_capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
        },
    )
    result = run_gta6_research(
        authorization_to_context(authorization),
    )

    return _json_result(
        operation="br_research_run",
        result=result,
    )


@mcp.tool()
def br_execution_process_next(
    goal_id: str | None = None,
    knowledge_id: int | None = None,
) -> str:
    """Advance one official production step under persisted Harness authority."""
    goal_id = _normalize_optional_goal_id(goal_id)
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="execute next official production video render step",
            authorized_action="EXECUTION",
            fallback_allowed=False,
        )
    )
    lineage = {
        "routing_id": routing.routing_id,
        "selected_capability_id": routing.selected_capability_id,
        "selected_executor_binding": routing.selected_executor_binding,
    }
    if goal_id is not None:
        lineage["goal_id"] = goal_id
    if knowledge_id is not None:
        if not isinstance(knowledge_id, int) or isinstance(knowledge_id, bool) or knowledge_id <= 0:
            raise ValueError("knowledge_id must be a positive integer or None")
        lineage["knowledge_id"] = knowledge_id
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        lineage=lineage,
    )
    execution_context = authorization_to_context(authorization)
    if goal_id is None:
        result = process_next_production_execution(execution_context)
    else:
        result = process_next_production_execution(
            execution_context,
            goal_id=goal_id,
            knowledge_id=knowledge_id,
        )
    evidence = canonical_execution_result(
        authority=authorization.authority,
        authorized_action=authorization.authorized_action,
        execution_id=authorization.execution_id,
        routing_id=routing.routing_id,
        authorization_id=authorization.authorization_id,
        harness_decision_id=authorization.harness_decision_id,
        capability_id=routing.selected_capability_id,
        tool="br_execution_process_next",
        operation="br_execution_process_next",
        provider=routing.selected_provider,
        model=routing.selected_model,
        executor=routing.selected_executor_binding,
        status="SUCCEEDED",
        success=True,
        result=result,
    )
    return _json_result(
        operation="br_execution_process_next",
        result=result,
        evidence=evidence,
    )


@mcp.tool()
def br_route(
    intent: str,
    authorized_action: str,
    required_capability_id: str | None = None,
    domain: str | None = None,
    preferred_provider: str | None = None,
    fallback_allowed: bool = False,
) -> str:
    """Return Harness routing metadata only; never authorize or execute."""
    decision = route_harness_request(
        HarnessRoutingRequest(
            intent=intent,
            authorized_action=authorized_action,
            domain=domain,
            required_capability_id=required_capability_id,
            provider_required=preferred_provider is not None,
            preferred_providers=(preferred_provider,) if preferred_provider else (),
            fallback_allowed=fallback_allowed,
        )
    )
    return _json_result(
        operation="br_route",
        result=decision,
    )


def _route_editorial_provider(
    goal_id: str | None = None,
    target_duration_seconds: float | None = None,
):
    """Route editorial AI under Harness policy before provider construction."""
    goal_id = _normalize_optional_goal_id(goal_id)
    target_duration_seconds = _normalize_optional_target_duration_seconds(
        target_duration_seconds
    )
    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="process next GTA6 editorial queue item with AI reasoning",
            authorized_action="EDITORIAL",
            domain="editorial",
            required_capability_id="editorial.process",
            provider_required=True,
            provider_domain="ai",
            fallback_allowed=False,
        )
    )
    if not decision.selected_provider:
        raise RuntimeError("Harness routing did not select the editorial AI provider")

    lineage = {
        "routing_id": decision.routing_id,
        "selected_capability_id": decision.selected_capability_id,
        "selected_provider": decision.selected_provider,
        "selected_model": decision.selected_model,
        "selected_executor_binding": decision.selected_executor_binding,
    }
    if goal_id is not None:
        lineage["goal_id"] = goal_id
    if target_duration_seconds is not None:
        lineage["target_duration_seconds"] = target_duration_seconds
    authorization = issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject=f"provider:{decision.selected_provider}",
        lineage=lineage,
    )
    _, provider = select_harness_ai_provider(
        routing_decision=decision,
        authorization=authorization,
    )
    return decision, authorization, provider


@mcp.tool()
def br_editorial_process_next(
    goal_id: str | None = None,
    target_duration_seconds: float | None = None,
) -> str:
    """Process the next editorial queue item through Harness routing/policy."""
    goal_id = _normalize_optional_goal_id(goal_id)
    target_duration_seconds = _normalize_optional_target_duration_seconds(
        target_duration_seconds
    )
    routing, provider_authorization, ai_provider = _route_editorial_provider(
        goal_id,
        target_duration_seconds,
    )

    lineage = {
        "routing_id": routing.routing_id,
        "selected_capability_id": routing.selected_capability_id,
        "selected_provider": routing.selected_provider,
        "selected_model": routing.selected_model,
        "selected_executor_binding": routing.selected_executor_binding,
        "provider_authorization_id": provider_authorization.authorization_id,
    }
    if goal_id is not None:
        lineage["goal_id"] = goal_id
    if target_duration_seconds is not None:
        lineage["target_duration_seconds"] = target_duration_seconds
    authorization = issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject="action:EDITORIAL",
        lineage=lineage,
    )

    result = process_next_editorial_queue_item(
        ai_provider=ai_provider,
        execution_context=authorization_to_context(authorization),
        goal_id=goal_id,
    )

    if result is None:
        result = {
            "status": "no_work",
            "executed": False,
            "reason": "Nenhum item queued disponível na fila editorial.",
        }
    else:
        result = dict(result)

    result["harness_routing"] = {
        "decision": routing.to_dict(),
        "authorization_id": authorization.authorization_id,
        "provider_authorization_id": provider_authorization.authorization_id,
    }

    return _json_result(
        operation="br_editorial_process_next",
        result=result,
    )


def _execute_master_cycle_under_harness() -> Any:
    """Route Brain inference first, then authorize exactly one recommended action."""
    provider_routing = route_harness_request(
        HarnessRoutingRequest(
            intent="decide the next GTA6 operational action",
            authorized_action="DECISION",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            fallback_allowed=False,
        )
    )
    if not provider_routing.selected_provider:
        raise RuntimeError("Harness routing did not select the Brain AI provider")

    provider_authorization = issue_harness_authorization(
        authorized_action="DECISION",
        subject=f"provider:{provider_routing.selected_provider}",
        lineage={
            "routing_id": provider_routing.routing_id,
            "selected_capability_id": provider_routing.selected_capability_id,
            "selected_provider": provider_routing.selected_provider,
            "selected_model": provider_routing.selected_model,
        },
    )
    _, provider = select_harness_ai_provider(
        routing_decision=provider_routing,
        authorization=provider_authorization,
    )
    agent = GTA6MasterAgent(ai_provider=provider)
    decision = agent.recommend()
    authorization = issue_harness_authorization(
        authorized_action=decision.action,
        subject=f"action:{decision.action}",
        lineage={
            "reason": decision.reason,
            "priority": decision.priority,
            "confidence": decision.confidence,
            "provider_routing_id": provider_routing.routing_id,
            "provider_authorization_id": provider_authorization.authorization_id,
        },
    )
    return agent.execute_authorized(decision, authorization)


@mcp.tool()
def br_gta6_monitor_run_once() -> str:
    """Execute one Harness-authorized GTA6 control cycle."""
    result = _execute_master_cycle_under_harness()
    return _json_result(
        operation="br_gta6_monitor_run_once",
        result=result,
    )


@mcp.tool()
def br_master_run_once() -> str:
    """Execute one official GTA6 control cycle under Harness authority."""
    result = _execute_master_cycle_under_harness()
    return _json_result(
        operation="br_master_run_once",
        result=result,
    )


@mcp.tool()
def br_capabilities_discover(
    intent: str,
    authorized_action: str,
) -> str:
    """
    Discover a small set of AVAILABLE capabilities relevant to Harness intent.

    This returns metadata only. It never injects every skill body and never
    authorizes execution by itself.
    """
    result = {
        "intent": intent,
        "authorized_action": authorized_action,
        "capabilities": discover_capabilities(
            intent=intent,
            authorized_action=authorized_action,
        ),
    }
    return _json_result(
        operation="br_capabilities_discover",
        result=result,
    )


@mcp.tool()
def br_capability_execute(
    capability_id: str,
    authorized_action: str,
    harness_decision_id: str | None = None,
    execution_id: str | None = None,
    payload_json: str = "{}",
) -> str:
    """
    Apply Harness capability policy and return execution evidence.

    The Harness binds either the existing selected SKILL executor or one
    explicitly allowlisted bounded EXECUTOR adapter. Generic EXECUTOR dispatch
    remains fail closed.
    """
    payload = json.loads(payload_json)
    if not isinstance(payload, dict):
        raise ValueError("payload_json must decode to an object")

    # Legacy caller-supplied IDs are accepted for wire compatibility only.
    # They are deliberately not trusted as authorization provenance.
    _ = (harness_decision_id, execution_id)

    try:
        routing = route_harness_request(
            HarnessRoutingRequest(
                intent=f"execute selected capability {capability_id}",
                authorized_action=authorized_action,
                required_capability_id=capability_id,
                fallback_allowed=False,
            )
        )
    except RoutingPolicyError as exc:
        required_state = exc.evidence.get("required_capability_state")
        availability = (
            required_state.get("availability")
            if isinstance(required_state, dict)
            else None
        )
        result_status = (
            availability
            if availability in {BLOCKED, UNKNOWN}
            else "UNAVAILABLE"
        )
        result = {
            "capability_id": capability_id,
            "status": result_status,
            "active": False,
            "authority": HARNESS_ISSUER,
            "authorized_action": authorized_action.strip().upper(),
            "authorization_id": None,
            "harness_decision_id": None,
            "execution_id": None,
            "result": {
                "stage": "routing",
                "error": str(exc),
                "routing_evidence": exc.evidence,
            },
            "boundary": (
                "Harness Routing/Policy rejected the implementation before "
                "authorization or execution"
            ),
        }
        canonical = canonical_execution_result(
            authority=HARNESS_ISSUER,
            authorized_action=authorized_action.strip().upper(),
            execution_id=None,
            capability_id=capability_id,
            tool="br_capability_execute",
            operation="br_capability_execute",
            status=result_status,
            success=False,
            result=result["result"],
            evidence={"routing": exc.evidence},
            error={"error": str(exc)},
        )
        return _json_result(
            operation="br_capability_execute",
            result=result,
            evidence=canonical,
        )

    implementation = routing.policy_metadata.get("selected_implementation")
    if not isinstance(implementation, dict):
        raise RuntimeError("Harness routing did not bind implementation metadata")

    authorization_lineage = {
        "routing_id": routing.routing_id,
        "capability_id": routing.selected_capability_id,
        "selected_agent_id": implementation.get("agent_id"),
        "selected_skill_id": implementation.get("skill_id"),
        "selected_executor_binding": routing.selected_executor_binding,
        "fallback_occurred": routing.fallback_occurred,
    }
    if routing.selected_capability_id == "agent-office.execute":
        goal_id = payload.get("goal_id")
        if not isinstance(goal_id, str) or not goal_id.strip():
            raise ValueError("Agent Office payload requires goal_id")
        authorization_lineage["goal_id"] = goal_id.strip()

    authorization = issue_harness_authorization(
        authorized_action=routing.authorized_action,
        subject=f"capability:{routing.selected_capability_id}",
        lineage=authorization_lineage,
    )
    capability_evidence = execute_mcp_capability(
        routing_decision=routing,
        authorization=authorization,
        payload=payload,
        implementation=implementation,
        skill_executor=execute_codex_addy_capability,
    )
    result = capability_evidence.to_dict()
    result["authorization_id"] = authorization.authorization_id
    result["harness_routing"] = {
        "routing_id": routing.routing_id,
        "requested_capability_id": capability_id,
        "selected_capability_id": routing.selected_capability_id,
        "selected_implementation": implementation,
        "selected_executor": routing.selected_executor_binding,
        "policy_reason": list(routing.rationale),
        "fallback_occurred": routing.fallback_occurred,
    }
    canonical = capability_evidence.to_canonical_result(
        authorization_id=authorization.authorization_id,
        routing_id=routing.routing_id,
        tool="br_capability_execute",
        operation="br_capability_execute",
        model=routing.selected_model,
        executor=routing.selected_executor_binding,
    )
    return _json_result(
        operation="br_capability_execute",
        result=result,
        evidence=canonical,
    )


@mcp.tool()
def br_youtube_publication_preview(publication_id: int) -> str:
    """Read exact publication readiness without granting publication authority."""
    result = build_youtube_publication_preview(publication_id)
    return _json_result(
        operation="br_youtube_publication_preview",
        result=result,
    )


@mcp.tool()
def br_youtube_publication_reconcile(publication_id: int) -> str:
    """Safely reconcile an uncertain prior user-approved public transition."""
    result = reconcile_youtube_publication_visibility_with_google(
        publication_id=publication_id,
    )
    return _json_result(
        operation="br_youtube_publication_reconcile",
        result=result,
    )


@mcp.tool()
def br_youtube_pode_postar(publication_id: int) -> str:
    """Execute explicit user approval for one exact uploaded Publication."""
    result = publish_targeted_publication(
        publication_id,
        approval_source="user",
        approval_operation="br_youtube_pode_postar",
    )
    return _json_result(
        operation="br_youtube_pode_postar",
        result=result,
    )


@mcp.tool()
def br_youtube_publish(publication_id: int) -> str:
    """Dispatch one exact Publication to the Harness-governed cloud uploader."""
    result = dispatch_targeted_private_upload(publication_id)
    return _json_result(
        operation="br_youtube_publish",
        result=result,
    )


@mcp.tool()
def br_youtube_publish_reconcile(publication_id: int) -> str:
    """Reconcile one exact private-upload cloud run into canonical state."""
    result = reconcile_targeted_private_upload(publication_id)
    return _json_result(
        operation="br_youtube_publish_reconcile",
        result=result,
    )


@mcp.tool()
def br_youtube_publish_next() -> str:
    """Run the next private YouTube upload under Harness authority."""
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="upload next pending YouTube publication as private",
            authorized_action="YOUTUBE",
            fallback_allowed=False,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="YOUTUBE",
        subject="action:YOUTUBE",
        lineage={
            "routing_id": routing.routing_id,
            "selected_capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
        },
    )
    result = process_next_youtube_publication(
        authorization_to_context(authorization),
    )
    return _json_result(
        operation="br_youtube_publish_next",
        result=result,
    )


def main() -> None:
    """Run the BR MCP server over stdio."""
    initialize_application()
    mcp.run(
        transport="stdio",
    )


if __name__ == "__main__":
    main()
