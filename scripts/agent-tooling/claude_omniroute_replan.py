from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[2]
for search_path in (REPO_ROOT, SCRIPT_DIR):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from claude_omniroute_route_plan import (
    HarnessProviderIdentity,
    ModelMappingUnavailable,
    build_route_plan,
    map_harness_target,
    mapped_harness_provider_ids,
)

FAILED_PROVIDER = "opencode"
FAILED_MODEL = "oc/big-pickle"
REQUIRED_MODEL_CAPABILITIES = ("reasoning", "coding", "structured_output")
EXCLUDED_FAILURE_CLASS = "UPSTREAM_DENIED_HTTP_403"


def replan_request_values() -> dict[str, Any]:
    return {
        "intent": "Claude Code governed development execution through OmniRoute",
        "authorized_action": "DEVELOPMENT",
        "required_capability_id": "ai.reasoning.text",
        "provider_required": True,
        "allowed_providers": mapped_harness_provider_ids(),
        "preferred_providers": (),
        "unavailable_provider_ids": (FAILED_PROVIDER,),
        "exhausted_provider_model_pairs": ((FAILED_PROVIDER, FAILED_MODEL),),
        "required_model_capabilities": REQUIRED_MODEL_CAPABILITIES,
        "fallback_allowed": False,
        "zero_cost_operation": True,
        "learning_required": False,
        "recovery_phase": "PROVIDER_LEVEL_REPLAN",
        "provider_level_replan_authorized": True,
        "from_provider": FAILED_PROVIDER,
    }


def omniroute_identity(provider: str, model: str) -> dict[str, str]:
    gateway_provider, gateway_model = map_harness_target(
        HarnessProviderIdentity(
            provider_id=str(provider or "").strip(),
            model_id=str(model or "").strip(),
        )
    )
    return {
        "provider": gateway_provider.provider_id,
        "model": gateway_model.model_id,
        "credential_env": gateway_provider.credential_env,
    }


def select_harness_replan(
    *,
    route_fn: Callable[[Any], Any] | None = None,
    request_cls: type | None = None,
) -> tuple[Any, dict[str, Any]]:
    if route_fn is None or request_cls is None:
        from app.services.harness_routing_policy_service import (
            HarnessRoutingRequest,
            route_harness_request,
        )
        route_fn = route_fn or route_harness_request
        request_cls = request_cls or HarnessRoutingRequest

    request = request_cls(**replan_request_values())
    decision = route_fn(request)
    provider = str(getattr(decision, "selected_provider", "") or "")
    model = str(getattr(decision, "selected_model", "") or "")
    if provider not in mapped_harness_provider_ids() or not model:
        raise RuntimeError("HARNESS_REPLAN_SELECTED_UNSUPPORTED_ROUTE")
    if bool(getattr(decision, "fallback_occurred", False)):
        raise RuntimeError("HARNESS_REPLAN_UNAUTHORIZED_FALLBACK")

    route_plan = build_route_plan(
        decision,
        required_capabilities=REQUIRED_MODEL_CAPABILITIES,
        strategy="priority",
        zero_cost=True,
        excluded_targets=(
            {
                "provider": FAILED_PROVIDER,
                "model": FAILED_MODEL,
                "failure_class": EXCLUDED_FAILURE_CLASS,
            },
        ),
        created_from_execution_need="SHARED_ROUTE_UNAVAILABLE",
    )
    evidence = {
        "schema": "ClaudeOmniRouteHarnessReplan/v2",
        "authority": "DEEPSEEK_HARNESS",
        "status": "ROUTE_PLAN_MATERIALIZED",
        "routing_id": str(getattr(decision, "routing_id", "") or ""),
        "selected_capability_id": str(
            getattr(decision, "selected_capability_id", "") or ""
        ),
        "selected_provider": provider,
        "selected_model": model,
        "logical_claude_model": route_plan["logical_claude_model"],
        "route_plan_id": route_plan["route_plan_id"],
        "route_plan_sha256": route_plan["route_plan_sha256"],
        "recovery_phase": "PROVIDER_LEVEL_REPLAN",
        "from_provider": FAILED_PROVIDER,
        "exhausted_provider_model_pairs": [[FAILED_PROVIDER, FAILED_MODEL]],
        "required_model_capabilities": list(REQUIRED_MODEL_CAPABILITIES),
        "fallback_allowed": False,
        "fallback_occurred": False,
        "route_plan": route_plan,
    }
    if not evidence["routing_id"]:
        raise RuntimeError("HARNESS_REPLAN_MISSING_ROUTING_ID")
    return decision, evidence


def _append_github_env(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            if "\n" in value or "\r" in value:
                raise ValueError(f"invalid multiline environment value for {key}")
            handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-path", type=Path, required=True)
    parser.add_argument("--route-plan-path", type=Path)
    parser.add_argument("--github-env", type=Path)
    args = parser.parse_args()

    _decision, evidence = select_harness_replan()
    route_plan = evidence["route_plan"]
    args.evidence_path.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_path.write_text(
        json.dumps(evidence, sort_keys=True), encoding="utf-8"
    )
    route_plan_path = (
        args.route_plan_path
        if args.route_plan_path is not None
        else args.evidence_path.parent / "route-plan.json"
    )
    route_plan_path.parent.mkdir(parents=True, exist_ok=True)
    route_plan_path.write_text(
        json.dumps(route_plan, sort_keys=True), encoding="utf-8"
    )

    first_target = route_plan["candidate_targets"][0]
    env_values = {
        "HARNESS_SELECTED_PROVIDER": str(evidence["selected_provider"]),
        "HARNESS_SELECTED_MODEL": str(evidence["selected_model"]),
        "HARNESS_OMNIROUTE_ROUTE_PLAN_ID": str(route_plan["route_plan_id"]),
        "HARNESS_OMNIROUTE_ROUTE_PLAN_SHA256": str(route_plan["route_plan_sha256"]),
        "HARNESS_MATERIALIZED_OMNIROUTE_ROUTE": str(
            route_plan["logical_claude_model"]
        ),
        "ANTHROPIC_MODEL": str(route_plan["logical_claude_model"]),
        "ANTHROPIC_CUSTOM_MODEL_OPTION": str(route_plan["logical_claude_model"]),
        "OMNIROUTE_PRIMARY_PROVIDER": str(first_target["omniroute_provider"]),
        "OMNIROUTE_PRIMARY_MODEL": str(first_target["omniroute_model"]),
        "OMNIROUTE_PRIMARY_CREDENTIAL_ENV": str(first_target["credential_env"]),
        "OMNIROUTE_COMBO_NAME": str(route_plan["omniroute_combo_name"]),
        "CLAUDE_OMNIROUTE_REPLAN_REQUIRED": "1",
    }
    if args.github_env is not None:
        _append_github_env(args.github_env, env_values)

    print("CLAUDE_OMNIROUTE_HARNESS_REPLAN=PASS")
    print("HARNESS_OMNIROUTE_ROUTE_PLAN=PASS")
    print("HARNESS_ROUTING_ID=" + str(evidence["routing_id"]))
    print("HARNESS_OMNIROUTE_ROUTE_PLAN_ID=" + str(route_plan["route_plan_id"]))
    print(
        "HARNESS_OMNIROUTE_ROUTE_PLAN_SHA256="
        + str(route_plan["route_plan_sha256"])
    )
    print(
        "HARNESS_MATERIALIZED_OMNIROUTE_ROUTE="
        + str(route_plan["logical_claude_model"])
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
