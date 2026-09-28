from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable

FAILED_PROVIDER = "opencode"
FAILED_MODEL = "oc/big-pickle"
ALLOWED_REPLAN_PROVIDERS = ("nvidia_nim",)
REQUIRED_MODEL_CAPABILITIES = ("reasoning", "coding", "structured_output")


def replan_request_values() -> dict[str, Any]:
    return {
        "intent": "Claude Code governed development execution through OmniRoute",
        "authorized_action": "DEVELOPMENT",
        "required_capability_id": "ai.reasoning.text",
        "provider_required": True,
        "allowed_providers": ALLOWED_REPLAN_PROVIDERS,
        "preferred_providers": ALLOWED_REPLAN_PROVIDERS,
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
    canonical_provider = str(provider or "").strip().lower().replace("-", "_")
    canonical_model = str(model or "").strip()
    if not canonical_model:
        raise ValueError("Harness-selected model is required")
    if canonical_provider == "nvidia_nim":
        return {
            "provider": "nvidia",
            "model": f"nvidia/{canonical_model}",
        }
    raise ValueError(
        f"Claude OmniRoute replan has no governed gateway mapping for provider={canonical_provider!r}"
    )


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
    if provider not in ALLOWED_REPLAN_PROVIDERS or not model:
        raise RuntimeError("HARNESS_REPLAN_SELECTED_UNSUPPORTED_ROUTE")
    if bool(getattr(decision, "fallback_occurred", False)):
        raise RuntimeError("HARNESS_REPLAN_UNAUTHORIZED_FALLBACK")

    gateway = omniroute_identity(provider, model)
    evidence = {
        "schema": "ClaudeOmniRouteHarnessReplan/v1",
        "authority": "DEEPSEEK_HARNESS",
        "status": "SELECTED",
        "routing_id": str(getattr(decision, "routing_id", "") or ""),
        "selected_capability_id": str(
            getattr(decision, "selected_capability_id", "") or ""
        ),
        "selected_provider": provider,
        "selected_model": model,
        "gateway_provider": gateway["provider"],
        "gateway_model": gateway["model"],
        "recovery_phase": "PROVIDER_LEVEL_REPLAN",
        "from_provider": FAILED_PROVIDER,
        "exhausted_provider_model_pairs": [[FAILED_PROVIDER, FAILED_MODEL]],
        "required_model_capabilities": list(REQUIRED_MODEL_CAPABILITIES),
        "fallback_allowed": False,
        "fallback_occurred": False,
    }
    policy_metadata = getattr(decision, "policy_metadata", None)
    if isinstance(policy_metadata, dict):
        snapshot = policy_metadata.get("provider_eligibility_snapshot")
        if isinstance(snapshot, dict):
            evidence["provider_eligibility_snapshot_ref"] = snapshot.get("snapshot_ref")
            evidence["provider_eligibility_snapshot_sha256"] = snapshot.get(
                "content_sha256"
            )
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
    parser.add_argument("--github-env", type=Path)
    args = parser.parse_args()

    if not str(os.getenv("NVIDIA_API_KEY") or "").strip():
        raise SystemExit("HARNESS_REPLAN_AUTH_UNAVAILABLE")

    _decision, evidence = select_harness_replan()
    args.evidence_path.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_path.write_text(
        json.dumps(evidence, sort_keys=True), encoding="utf-8"
    )

    env_values = {
        "HARNESS_SELECTED_PROVIDER": str(evidence["selected_provider"]),
        "HARNESS_SELECTED_MODEL": str(evidence["selected_model"]),
        "OMNIROUTE_SELECTED_PROVIDER": str(evidence["gateway_provider"]),
        "OMNIROUTE_SELECTED_MODEL": str(evidence["gateway_model"]),
        "ANTHROPIC_MODEL": str(evidence["gateway_model"]),
        "ANTHROPIC_CUSTOM_MODEL_OPTION": str(evidence["gateway_model"]),
        "CLAUDE_OMNIROUTE_REPLAN_REQUIRED": "1",
    }
    if args.github_env is not None:
        _append_github_env(args.github_env, env_values)

    print("CLAUDE_OMNIROUTE_HARNESS_REPLAN=PASS")
    print("HARNESS_ROUTING_ID=" + str(evidence["routing_id"]))
    print("HARNESS_SELECTED_PROVIDER=" + str(evidence["selected_provider"]))
    print("HARNESS_SELECTED_MODEL=" + str(evidence["selected_model"]))
    print("OMNIROUTE_SELECTED_PROVIDER=" + str(evidence["gateway_provider"]))
    print("OMNIROUTE_SELECTED_MODEL=" + str(evidence["gateway_model"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
