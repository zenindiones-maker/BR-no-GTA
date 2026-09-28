from __future__ import annotations

import argparse
from urllib.parse import urlparse

DEFAULT_BASE_URL = "http://127.0.0.1:20128"
DEFAULT_LOCAL_TOKEN = "omniroute-no-auth"


def _explicit(value: str, *, label: str) -> str:
    resolved = str(value or "").strip()
    if not resolved or resolved == "auto" or resolved.startswith("auto/"):
        raise ValueError(f"{label} must be explicit")
    return resolved


def _validate_loopback_root(base_url: str) -> str:
    parsed = urlparse(str(base_url or "").strip())
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Claude Code OmniRoute gateway must be loopback HTTP")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("ANTHROPIC_BASE_URL must be the gateway root without /v1")
    if parsed.port != 20128:
        raise ValueError("Claude Code OmniRoute proof requires port 20128")
    return str(base_url).rstrip("/")


def build_gateway_env(*, provider: str, model: str, base_url: str = DEFAULT_BASE_URL, auth_token: str | None = None) -> dict[str, str]:
    _explicit(provider, label="provider")
    selected_model = _explicit(model, label="model")
    root = _validate_loopback_root(base_url)
    return {
        "ANTHROPIC_BASE_URL": root,
        "ANTHROPIC_AUTH_TOKEN": str(auth_token or DEFAULT_LOCAL_TOKEN),
        "ANTHROPIC_MODEL": selected_model,
        "ANTHROPIC_CUSTOM_MODEL_OPTION": selected_model,
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "190000",
    }


def validate_zero_cost_proof_selection(provider: str, model: str) -> tuple[str, str]:
    selected_provider = _explicit(provider, label="provider")
    selected_model = _explicit(model, label="model")
    if selected_provider != "opencode" or selected_model != "oc/big-pickle":
        raise ValueError("zero-cost Claude Code proof is pinned to opencode/oc/big-pickle")
    return selected_provider, selected_model


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--zero-cost-proof", action="store_true")
    args = parser.parse_args()
    if args.zero_cost_proof:
        validate_zero_cost_proof_selection(args.provider, args.model)
    env = build_gateway_env(provider=args.provider, model=args.model, base_url=args.base_url)
    print(f"CLAUDE_OMNIROUTE_BASE_URL={env['ANTHROPIC_BASE_URL']}")
    print(f"CLAUDE_OMNIROUTE_MODEL={env['ANTHROPIC_MODEL']}")
    print("CLAUDE_OMNIROUTE_AUTH=LOCAL_SENTINEL")
    print("CLAUDE_OMNIROUTE_CONTRACT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
