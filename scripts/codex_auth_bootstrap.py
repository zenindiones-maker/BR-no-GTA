from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.services.agent_office.codex_auth import (
    CodexAuthenticationProvider,
    write_auth_status,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-device-auth", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=2700)
    args = parser.parse_args()

    codex_home = os.getenv("CODEX_HOME")
    if not codex_home:
        raise RuntimeError("CODEX_HOME must be isolated before trusted auth bootstrap")
    home = Path(codex_home)
    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)

    state = CodexAuthenticationProvider().bootstrap(
        cwd=Path.cwd(),
        timeout=args.timeout_seconds,
        allow_device_auth=args.allow_device_auth,
    )
    write_auth_status(args.output, state)

    print("CODEX_AUTH_PREREQUISITE=" + ("AVAILABLE" if state.available else "BLOCKED"))
    print(f"CODEX_AUTH_METHOD_SELECTED={state.method}")
    print(f"CODEX_AUTH_COST_CLASS={state.cost_class}")
    print(
        "CODEX_AUTH_USER_ACTION_REQUIRED="
        + ("YES" if state.user_action_required else "NO")
    )
    print("CODEX_AUTH_SECRET_LEAK=" + ("YES" if state.secret_leak else "NO"))
    return 0 if state.available else 2


if __name__ == "__main__":
    raise SystemExit(main())
