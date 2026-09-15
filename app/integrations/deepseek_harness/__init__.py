"""DeepSeek Harness integration for BR-no-GTA.

The package installs the editorial-provider routing compatibility boundary after
loading the MCP server. Editorial queue execution remains the governed
``editorial.process`` operation, while AI construction is routed independently
through the canonical ``ai.reasoning.text`` capability as required by the
provider boundary.
"""

from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_ai_provider_service import select_harness_ai_provider
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)

from . import server as _server


def _route_editorial_ai_provider(
    goal_id: str | None = None,
    target_duration_seconds: float | None = None,
):
    """Route only the editorial AI provider through ``ai.reasoning.text``.

    The editorial action itself is still authorized separately by
    ``br_editorial_process_next``.  This avoids treating the editorial skill as
    an AI-provider capability while preserving the single Harness authority and
    zero-cost provider policy.
    """
    goal_id = _server._normalize_optional_goal_id(goal_id)
    target_duration_seconds = _server._normalize_optional_target_duration_seconds(
        target_duration_seconds
    )
    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="provide AI reasoning for the next GTA6 editorial queue item",
            authorized_action="EDITORIAL",
            domain="ai",
            required_capability_id="ai.reasoning.text",
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
        "editorial_capability_id": "editorial.process",
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


# ``br_editorial_process_next`` resolves this global at execution time.  Patch
# the legacy combined route without duplicating or bypassing the MCP authority.
_server._route_editorial_provider = _route_editorial_ai_provider
