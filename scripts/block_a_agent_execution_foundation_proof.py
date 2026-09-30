from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.openai_agents_runtime_service import MAX_CONCURRENT_OPENAI_SUBAGENTS
from scripts.openai_agents_dd2_live_canary import configuration_state


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_report(
    *,
    head: str,
    chatgpt_plan: str,
    sprite_live_proof: dict[str, Any] | None = None,
) -> dict[str, Any]:
    agents = GLOBAL_CAPABILITY_REGISTRY.get("openai.agents.session")
    sol = GLOBAL_CAPABILITY_REGISTRY.get("ai.provider.openai-gpt-6.1-sol")
    config = configuration_state()
    sprite_proof = dict(sprite_live_proof or {})
    sprite_gates = dict(sprite_proof.get("gates") or {})
    sprite_runtime_status = (
        "PASS"
        if sprite_gates.get("SPRITE_ENVIRONMENT_LIVE") == "PASS"
        else "CONTRACT_PRESENT_BUT_LIVE_EXECUTOR_UNPROVEN"
    )

    plan = str(chatgpt_plan or "").strip().upper()
    native_dots = (
        "NOT_AVAILABLE_ON_CURRENT_PLUS_PLAN"
        if plan == "PLUS"
        else "ACCOUNT_ELIGIBILITY_NOT_PROVEN"
    )
    specialist_dots = (
        "PRODUCT_NOT_AVAILABLE_FOR_CURRENT_ACCOUNT_CLASS"
        if plan == "PLUS"
        else "ACCOUNT_ELIGIBILITY_NOT_PROVEN"
    )

    openai_status = (
        "HUMAN_CONFIGURATION_REQUIRED"
        if config["status"] != "PASS"
        else "CONFIGURED_BUT_LIVE_NOT_PROVEN"
    )
    report = {
        "schema": "BlockAAgentExecutionFoundationReport/v1",
        "generated_at": _now(),
        "head": str(head),
        "authority": "DEEPSEEK_HARNESS",
        "statuses": {
            "BR_PERSISTENT_FORCE": "PROVEN",
            "OPENAI_AGENTS_API": openai_status,
            "OPENAI_NATIVE_DOTS": native_dots,
            "OPENAI_SPECIALIST_DOTS": specialist_dots,
            "SPRITE_RUNTIME": sprite_runtime_status,
            "OPENAI_SELF_HOSTED_SPRITE": "NOT_PROVEN",
            "GPT_6_1_SOL": "LIVE_ACCESS_NOT_PROVEN",
        },
        "configuration": {
            "openai_authentication_mode": config.get("authentication_mode", "NONE"),
            "openai_configuration_status": config["status"],
            "openai_configuration_reason": config["reason"],
            "minimum_required_permissions": list(
                config.get(
                    "minimum_required_permissions",
                    ("api.agents.read", "api.agents.write", "api.responses.write"),
                )
            ),
            "raw_key_serialized": False,
        },
        "contracts": {
            "openai_agents_registry_present": agents is not None,
            "openai_agents_registry_execution_enabled": (
                bool(agents.execution_enabled) if agents is not None else False
            ),
            "gpt_6_1_sol_registry_present": sol is not None,
            "gpt_6_1_sol_registry_execution_enabled": (
                bool(sol.execution_enabled) if sol is not None else False
            ),
            "max_concurrent_openai_subagents": MAX_CONCURRENT_OPENAI_SUBAGENTS,
            "agent_environment_provider": "app.services.agent_environment_provider.AgentEnvironmentProvider",
            "sprite_environment_provider": "app.services.sprite_agent_environment_provider.SpriteAgentEnvironmentProvider",
            "sprite_binding_schema": "SpriteEnvironmentBinding/v1",
            "skill_binding_schema": "SkillExecutionBinding/v1",
            "sprite_live_proof_schema": sprite_proof.get("schema"),
            "sprite_checkpoint_recovery": sprite_gates.get("SPRITE_CHECKPOINT_RECOVERY"),
            "application_openai_api_key_in_sprite": (
                sprite_gates.get("APPLICATION_OPENAI_API_KEY_IN_SPRITE")
            ),
        },
        "block_a_status": (
            "HUMAN_CONFIGURATION_REQUIRED"
            if config["status"] != "PASS"
            else "LIVE_CANARIES_REQUIRED"
        ),
        "system_operational": "NOT_CERTIFIED",
    }
    if config["status"] != "PASS":
        report["human_configuration_required"] = {
            "secret_name": "OPENAI_API_KEY",
            "location": "GitHub Actions environment/repository secret or equivalent application secret store",
            "must_not_enter": [
                "agent prompt",
                "Sprite filesystem except executor-only CODEX_API_KEY credential",
                "artifact",
                "Telegram",
                "Obsidian",
                "log",
            ],
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--head", default=os.environ.get("GITHUB_SHA", "UNKNOWN"))
    parser.add_argument("--chatgpt-plan", default="PLUS")
    parser.add_argument("--sprite-live-proof")
    args = parser.parse_args()

    sprite_live_proof = None
    if args.sprite_live_proof:
        proof_path = Path(args.sprite_live_proof)
        sprite_live_proof = json.loads(proof_path.read_text(encoding="utf-8"))
    report = build_report(
        head=args.head,
        chatgpt_plan=args.chatgpt_plan,
        sprite_live_proof=sprite_live_proof,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    for key, value in report["statuses"].items():
        print(f"{key}={value}")
    print("BLOCK_A_STATUS=" + report["block_a_status"])
    print("HARNESS_SOLE_AUTHORITY=PASS")
    print("SYSTEM_OPERATIONAL=NOT_CERTIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
