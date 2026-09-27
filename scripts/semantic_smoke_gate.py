from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

from app.database.schema import initialize_schema
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_ai_provider_service import execute_harness_ai_generation
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    initialize_schema()
    if not str(os.getenv("NVIDIA_API_KEY") or "").strip():
        raise RuntimeError("SEMANTIC_SMOKE_SECRET_BLOCKER:NVIDIA_API_KEY")
    started = time.perf_counter()
    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="minimal pre-live semantic smoke for governed zero-cost NVIDIA provider",
            authorized_action="EDITORIAL",
            domain="ai",
            task_class="prelive-semantic-smoke",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            preferred_providers=("nvidia_nim",),
            allowed_providers=("nvidia_nim",),
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=False,
        )
    )
    if decision.selected_provider != "nvidia_nim":
        raise RuntimeError(
            f"semantic smoke routed unexpected provider: {decision.selected_provider}"
        )

    authorization = issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject="provider:nvidia_nim",
        harness_decision_id="prelive-semantic-smoke",
        execution_id="prelive-semantic-smoke",
        lineage={
            "routing_id": decision.routing_id,
            "capability_id": decision.selected_capability_id,
            "selected_provider": decision.selected_provider,
            "selected_model": decision.selected_model,
            "selected_executor_binding": decision.selected_provider_executor_binding,
        },
    )
    try:
        evidence = execute_harness_ai_generation(
            prompt="Return exactly this token and nothing else: BR_SEMANTIC_SMOKE_OK",
            authorization=authorization,
            routing_decision=decision,
        )
    finally:
        consume_harness_authorization(authorization)

    text = str((evidence.result or {}).get("text") or "").strip()
    if evidence.status != "EXECUTED" or "BR_SEMANTIC_SMOKE_OK" not in text:
        raise RuntimeError(
            "semantic smoke failed: "
            + json.dumps(
                {
                    "status": evidence.status,
                    "provider": evidence.provider,
                    "model": evidence.model,
                    "error": evidence.error,
                    "text_prefix": text[:160],
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        )

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    result = {
        "status": "PASS",
        "SEMANTIC_SMOKE": "PASS",
        "provider": evidence.provider,
        "model": evidence.model,
        "routing_id": decision.routing_id,
        "latency_ms": round(elapsed_ms, 3),
        "fallback_occurred": decision.fallback_occurred,
        "evidence_refs": list(evidence.evidence_refs),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("SEMANTIC_SMOKE=PASS")
    print(f"SEMANTIC_SMOKE_MS={elapsed_ms:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
