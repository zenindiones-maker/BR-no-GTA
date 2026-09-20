from __future__ import annotations

import json
from typing import Any


OPENCODE_SEMANTIC_AGENT_ID = "semantic-text"
OPENCODE_SEMANTIC_PROFILE_VERSION = "opencode-semantic-text-v3"
OPENCODE_SEMANTIC_MAX_STEPS = 1
OPENCODE_SEMANTIC_CONTRACT = "SEMANTIC_TEXT_ONLY"


def semantic_text_only_config() -> dict[str, Any]:
    """Native OpenCode V2 config for text-only semantic reasoning.

    steps=1 is intentional: on the final step OpenCode removes tools from the
    model request. Deny-all permissions remain as a second fail-closed boundary.
    """
    deny_all = [
        {"action": "*", "resource": "*", "effect": "deny"},
    ]
    return {
        "$schema": "https://opencode.ai/config.json",
        "default_agent": OPENCODE_SEMANTIC_AGENT_ID,
        "permissions": deny_all,
        "agents": {
            OPENCODE_SEMANTIC_AGENT_ID: {
                "description": (
                    "BR-no-GTA Harness semantic text-only reasoning. "
                    "No tools, no filesystem, no shell, no browser, no network."
                ),
                "mode": "primary",
                "steps": OPENCODE_SEMANTIC_MAX_STEPS,
                "system": (
                    "You are a text-only semantic reasoning provider. "
                    "Use only the context supplied in the user prompt. "
                    "Return the requested final text directly. "
                    "Do not request or use tools, files, shell, browser, network, "
                    "subagents, skills, or external state."
                ),
                "permissions": deny_all,
            }
        },
    }


def semantic_text_only_config_json() -> str:
    return json.dumps(
        semantic_text_only_config(),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def semantic_profile_evidence() -> dict[str, Any]:
    return {
        "profile_version": OPENCODE_SEMANTIC_PROFILE_VERSION,
        "semantic_agent": OPENCODE_SEMANTIC_AGENT_ID,
        "semantic_contract": OPENCODE_SEMANTIC_CONTRACT,
        "semantic_steps": OPENCODE_SEMANTIC_MAX_STEPS,
        "permissions": "deny-all",
        "tool_exposure_contract": "final-step-tools-removed-by-opencode",
    }
