from __future__ import annotations

import argparse
import re
from urllib.parse import urlparse

DEFAULT_BASE_URL = "http://127.0.0.1:20128"
DEFAULT_LOCAL_TOKEN = "omniroute-no-auth"
LOGICAL_ROUTE_RE = re.compile(r"^combo/harness-claude-[0-9a-f]{16}$")


def _validate_logical_route(value: str) -> str:
    resolved = str(value or "").strip()
    if not LOGICAL_ROUTE_RE.fullmatch(resolved):
        raise ValueError(
            "Claude Code must target a Harness-materialized logical combo alias"
        )
    return resolved


def _validate_loopback_root(base_url: str) -> str:
    parsed = urlparse(str(base_url or "").strip())
    if parsed.scheme != "http" or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ValueError("Claude Code OmniRoute gateway must be loopback HTTP")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("ANTHROPIC_BASE_URL must be the gateway root without /v1")
    if parsed.port != 20128:
        raise ValueError("Claude Code OmniRoute proof requires port 20128")
    return str(base_url).rstrip("/")


def build_gateway_env(
    *,
    logical_model: str,
    base_url: str = DEFAULT_BASE_URL,
    auth_token: str | None = None,
    proof_mode: bool = False,
) -> dict[str, str]:
    selected_model = _validate_logical_route(logical_model)
    root = _validate_loopback_root(base_url)

    if proof_mode:
        token = DEFAULT_LOCAL_TOKEN
        auth_mode = "PROOF_LOOPBACK_SENTINEL"
    else:
        token = str(auth_token or "").strip()
        if not token:
            raise ValueError(
                "production OmniRoute endpoint auth requires a scoped inference key"
            )
        auth_mode = "SCOPED_INFERENCE_KEY"

    return {
        "ANTHROPIC_BASE_URL": root,
        "ANTHROPIC_AUTH_TOKEN": token,
        "ANTHROPIC_MODEL": selected_model,
        "ANTHROPIC_CUSTOM_MODEL_OPTION": selected_model,
        "OMNIROUTE_ENDPOINT_AUTH_MODE": auth_mode,
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "190000",
    }


def validate_zero_cost_proof_selection(logical_model: str) -> str:
    return _validate_logical_route(logical_model)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--logical-model", required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--proof-mode", action="store_true")
    args = parser.parse_args()

    env = build_gateway_env(
        logical_model=args.logical_model,
        base_url=args.base_url,
        proof_mode=args.proof_mode,
    )
    print(f"CLAUDE_OMNIROUTE_BASE_URL={env['ANTHROPIC_BASE_URL']}")
    print(f"CLAUDE_OMNIROUTE_MODEL={env['ANTHROPIC_MODEL']}")
    print("CLAUDE_OMNIROUTE_AUTH=" + env["OMNIROUTE_ENDPOINT_AUTH_MODE"])
    print("CLAUDE_OMNIROUTE_CONTRACT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
