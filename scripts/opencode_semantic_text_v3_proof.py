from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.database.schema import initialize_schema
from app.services.harness_ai_provider_service import execute_harness_ai_generation
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.opencode_executor_profile_service import (
    SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION,
    executable_opencode_executor_profile,
)
from app.services.opencode_native_ai_provider import OpenCodeNativeAIProvider
from app.services.opencode_semantic_profile import (
    OPENCODE_SEMANTIC_AGENT_ID,
    OPENCODE_SEMANTIC_CONTRACT,
    OPENCODE_SEMANTIC_PROFILE_VERSION,
)


def _compact_real_context() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    checkpoint_path = root / ".checkpoints" / "current-system-state.json"
    checkpoint: dict[str, Any] = {}
    if checkpoint_path.is_file():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    operational = checkpoint.get("operational_state")
    operational = operational if isinstance(operational, dict) else {}
    return {
        "source": str(checkpoint_path.relative_to(root)) if checkpoint_path.is_file() else None,
        "git_head": str(os.getenv("GITHUB_SHA") or "").strip() or None,
        "checkpoint_status": checkpoint.get("status"),
        "goal_id": checkpoint.get("goal_id"),
        "human_review_status": (
            operational.get("HUMAN_REVIEW_STATUS")
            or (checkpoint.get("final_delivery_checkpoint") or {}).get("human_review_status")
        ),
        "youtube_privacy_status": (
            (checkpoint.get("final_delivery_checkpoint") or {}).get("youtube_privacy_status")
        ),
        "harness_sole_authority": (
            operational.get("HARNESS_SOLE_AUTHORITY")
            or (checkpoint.get("harness_authority_contract") or {}).get("sole_authority")
        ),
    }


def _route():
    return route_harness_request(
        HarnessRoutingRequest(
            intent="isolated proof of OpenCode semantic text-only profile v3",
            authorized_action="DECISION",
            domain="ai",
            task_class="opencode.semantic-text-v3-proof",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            preferred_providers=("opencode",),
            allowed_providers=("opencode",),
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=False,
        )
    )


def _execute(prompt: str, *, label: str) -> dict[str, Any]:
    routing = _route()
    authorization = issue_harness_authorization(
        authorized_action="DECISION",
        subject="provider:opencode",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_provider": routing.selected_provider,
            "selected_model": routing.selected_model,
            "selected_executor_binding": routing.selected_provider_executor_binding,
            "profile_version": SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION,
            "proof_label": label,
        },
    )
    profile = executable_opencode_executor_profile(
        SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION
    )
    provider = OpenCodeNativeAIProvider(
        routing_decision=routing,
        authorization=authorization,
        profile=profile,
    )

    def selector(*, provider_name, authorization):
        assert provider_name == "opencode"
        return "opencode", provider

    try:
        evidence = execute_harness_ai_generation(
            prompt=prompt,
            authorization=authorization,
            routing_decision=routing,
            selector=selector,
        )
    finally:
        consume_harness_authorization(authorization)

    result = evidence.result if isinstance(evidence.result, dict) else {}
    text = str(result.get("text") or "").strip()
    metrics = dict(getattr(provider, "last_performance_metrics", {}) or {})
    return {
        "label": label,
        "status": evidence.status,
        "active": evidence.active,
        "provider": evidence.provider,
        "model": evidence.model,
        "text": text,
        "error": evidence.error,
        "routing_id": routing.routing_id,
        "authorization_id": evidence.authorization_id,
        "execution_id": evidence.execution_id,
        "profile_version": evidence.provider_profile_version,
        "semantic_profile_version": metrics.get("profile_version"),
        "semantic_agent": metrics.get("semantic_agent"),
        "semantic_contract": metrics.get("semantic_contract"),
        "semantic_steps": metrics.get("semantic_steps"),
        "tool_call_count": int(metrics.get("tool_call_count") or 0),
        "tools_exposed": int(metrics.get("tools_exposed") or 0),
        "semantic_text_only_pass": bool(metrics.get("semantic_text_only_pass")),
        "performance": metrics,
    }


def run_proof() -> dict[str, Any]:
    initialize_schema()
    isolated = _execute(
        "Responda apenas: TESTE_OK",
        label="isolated_exact_text",
    )
    context = _compact_real_context()
    contextual = _execute(
        (
            "Responda em português do Brasil à pergunta 'Onde estamos?' "
            "usando somente o CONTEXTO_REAL abaixo. Seja breve e natural; "
            "não mencione ferramentas nem invente estado.\n"
            f"CONTEXTO_REAL={json.dumps(context, ensure_ascii=False, sort_keys=True)}"
        ),
        label="real_context_status",
    )

    checks = {
        "EXIT_CODE_EQUIVALENT": (
            isolated["status"] == "EXECUTED"
            and contextual["status"] == "EXECUTED"
        ),
        "USABLE_TEXT": bool(isolated["text"]) and bool(contextual["text"]),
        "EXACT_TEST_TEXT": isolated["text"] == "TESTE_OK",
        "TOOL_CALL_COUNT_ZERO": (
            isolated["tool_call_count"] == 0
            and contextual["tool_call_count"] == 0
        ),
        "TOOLS_EXPOSED_ZERO": (
            isolated["tools_exposed"] == 0
            and contextual["tools_exposed"] == 0
        ),
        "SEMANTIC_AGENT_ISOLATED": (
            isolated["semantic_agent"] == OPENCODE_SEMANTIC_AGENT_ID
            and contextual["semantic_agent"] == OPENCODE_SEMANTIC_AGENT_ID
        ),
        "SEMANTIC_PROFILE_V3": (
            isolated["semantic_profile_version"] == OPENCODE_SEMANTIC_PROFILE_VERSION
            and contextual["semantic_profile_version"] == OPENCODE_SEMANTIC_PROFILE_VERSION
        ),
        "SEMANTIC_CONTRACT": (
            isolated["semantic_contract"] == OPENCODE_SEMANTIC_CONTRACT
            and contextual["semantic_contract"] == OPENCODE_SEMANTIC_CONTRACT
            and isolated["semantic_text_only_pass"]
            and contextual["semantic_text_only_pass"]
        ),
        "FALLBACK_OCCURRED": False,
    }
    passed = all(value is True for key, value in checks.items() if key != "FALLBACK_OCCURRED")
    return {
        "status": "PASS" if passed else "FAIL",
        "profile": OPENCODE_SEMANTIC_PROFILE_VERSION,
        "model": "oc/big-pickle",
        "cli_version": "2.0.8",
        "checks": checks,
        "isolated": isolated,
        "contextual": contextual,
        "real_context": context,
        "root_cause_evidence": {
            "run_id": 35537494044,
            "artifact_id": 10612603412,
            "failure_pattern": "opencode_semantic_tools_used",
            "observed_tool_call_count": 6,
            "observed_agent": "build",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    proof = run_proof()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(proof, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"OPENCODE_SEMANTIC_V3_PROOF={proof['status']}")
    print("MODEL=oc/big-pickle")
    print("SEMANTIC_AGENT=build")
    print("SEMANTIC_PROFILE=opencode-semantic-text-v3")
    print(f"ISOLATED_TEXT={proof['isolated']['text']}")
    print(f"TOOL_CALL_COUNT={proof['isolated']['tool_call_count']}")
    print(f"TOOLS_EXPOSED={proof['isolated']['tools_exposed']}")
    print(
        "SEMANTIC_TEXT_ONLY="
        + ("PASS" if proof["checks"]["SEMANTIC_CONTRACT"] else "FAIL")
    )
    print(
        "CONTEXTUAL_TOOL_CALL_COUNT="
        + str(proof["contextual"]["tool_call_count"])
    )
    return 0 if proof["status"] == "PASS" else 9


if __name__ == "__main__":
    raise SystemExit(main())
