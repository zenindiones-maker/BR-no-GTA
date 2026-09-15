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
    make_youtube_publication_public_with_google,
    process_next_youtube_publication,
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
def br_execution_process_next() -> str:
    """Advance one official production step under persisted Harness authority."""
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="execute next official production video render step",
            authorized_action="EXECUTION",
            fallback_allowed=False,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        lineage={
            "routing_id": routing.routing_id,
            "selected_capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
        },
    )
    result = process_next_production_execution(
        authorization_to_context(authorization),
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


def _route_editorial_provider():
    """Route editorial AI under Harness policy before provider construction."""
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

    authorization = issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject=f"provider:{decision.selected_provider}",
        lineage={
            "routing_id": decision.routing_id,
            "selected_capability_id": decision.selected_capability_id,
            "selected_provider": decision.selected_provider,
            "selected_model": decision.selected_model,
            "selected_executor_binding": decision.selected_executor_binding,
        },
    )
    _, provider = select_harness_ai_provider(
        routing_decision=decision,
        authorization=authorization,
    )
    return decision, authorization, provider


@mcp.tool()
def br_editorial_process_next() -> str:
    """Process the next editorial queue item through Harness routing/policy."""
    routing, provider_authorization, ai_provider = _route_editorial_provider()

    authorization = issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject="action:EDITORIAL",
        lineage={
            "routing_id": routing.routing_id,
            "selected_capability_id": routing.selected_capability_id,
            "selected_provider": routing.selected_provider,
            "selected_model": routing.selected_model,
            "selected_executor_binding": routing.selected_executor_binding,
            "provider_authorization_id": provider_authorization.authorization_id,
        },
    )

    result = process_next_editorial_queue_item(
        ai_provider=ai_provider,
        execution_context=authorization_to_context(authorization),
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

    authorization = issue_harness_authorization(
        authorized_action=routing.authorized_action,
        subject=f"capability:{routing.selected_capability_id}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_agent_id": implementation.get("agent_id"),
            "selected_skill_id": implementation.get("skill_id"),
            "selected_executor_binding": routing.selected_executor_binding,
            "fallback_occurred": routing.fallback_occurred,
        },
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
def br_youtube_pode_postar(publication_id: int) -> str:
    """
    Explicit authorization gate for public YouTube publication.

    This operation is intentionally separate from the GTA6 Brain YOUTUBE
    action. YOUTUBE may upload pending content, while this operation
    authorizes the existing uploaded -> published transition.
    """
    authorization = issue_harness_authorization(
        authorized_action="PUBLICATION",
        subject=f"youtube:publication:{publication_id}",
        lineage={"publication_id": publication_id},
    )
    result = make_youtube_publication_public_with_google(
        publication_id=publication_id,
        authorization=authorization,
    )
    return _json_result(
        operation="br_youtube_pode_postar",
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
