from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping

from app.services.agent_office.codex_bounded_worker import codex_sanitized_environment


Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class CodexAuthenticationState:
    available: bool
    method: str
    cost_class: str
    user_action_required: bool
    exit_code: int
    secret_leak: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "method": self.method,
            "cost_class": self.cost_class,
            "user_action_required": self.user_action_required,
            "exit_code": self.exit_code,
            "account_identity_recorded": False,
            "secret_recorded": False,
            "secret_leak": self.secret_leak,
        }


def _stored_method(status_text: str) -> tuple[str, str]:
    lowered = status_text.lower()
    if "api key" in lowered or "apikey" in lowered:
        return "api_key_cached", "paid_api"
    if "access token" in lowered:
        return "access_token_cached", "workspace_entitlement"
    if "chatgpt" in lowered:
        return "chatgpt_cached", "subscription_or_workspace"
    return "cached_login", "unknown_existing"


class CodexAuthenticationProvider:
    """Trusted Codex auth boundary using official persisted/WIF/device flows."""

    def __init__(
        self,
        *,
        runner: Runner = subprocess.run,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._runner = runner
        self._environ = dict(os.environ if environ is None else environ)

    def _run(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout: float,
        env: Mapping[str, str],
        passthrough: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return self._runner(
            command,
            cwd=cwd,
            timeout=timeout,
            check=False,
            text=True,
            env=dict(env),
            capture_output=not passthrough,
        )

    def _status(self, *, cwd: Path, timeout: float, env: Mapping[str, str]):
        return self._run(
            ["codex", "login", "status"],
            cwd=cwd,
            timeout=timeout,
            env=env,
        )

    def bootstrap(
        self,
        *,
        cwd: Path,
        timeout: float = 900,
        allow_device_auth: bool = False,
    ) -> CodexAuthenticationState:
        source = self._environ
        trusted_env = codex_sanitized_environment(source)
        zero_cost = str(source.get("ZERO_COST_OPERATION", "")).upper() == "TRUE"

        federation_rule = source.get("OPENAI_FEDERATION_RULE_ID", "").strip()
        identity_file = source.get("OPENAI_IDENTITY_TOKEN_FILE", "").strip()
        if bool(federation_rule) != bool(identity_file):
            return CodexAuthenticationState(
                available=False,
                method="workload_identity_incomplete",
                cost_class="workspace_managed_short_lived",
                user_action_required=True,
                exit_code=2,
            )

        status = self._status(cwd=cwd, timeout=timeout, env=trusted_env)
        if status.returncode == 0:
            method, cost_class = _stored_method(
                f"{status.stdout or ''}\n{status.stderr or ''}"
            )
            if federation_rule and identity_file:
                method = "workload_identity"
                cost_class = "workspace_managed_short_lived"
            if zero_cost and cost_class == "paid_api":
                return CodexAuthenticationState(
                    available=False,
                    method=method,
                    cost_class=cost_class,
                    user_action_required=True,
                    exit_code=3,
                )
            return CodexAuthenticationState(
                available=True,
                method=method,
                cost_class=cost_class,
                user_action_required=False,
                exit_code=0,
            )

        if not allow_device_auth:
            return CodexAuthenticationState(
                available=False,
                method="none",
                cost_class="none",
                user_action_required=True,
                exit_code=status.returncode,
            )

        print("CODEX_DEVICE_AUTH_REQUIRED=YES", flush=True)
        print("CODEX_AUTH_METHOD_SELECTED=device_auth", flush=True)
        print("CODEX_AUTH_COST_CLASS=subscription_or_workspace", flush=True)
        device = self._run(
            ["codex", "login", "--device-auth"],
            cwd=cwd,
            timeout=timeout,
            env=trusted_env,
            passthrough=True,
        )
        if device.returncode != 0:
            return CodexAuthenticationState(
                available=False,
                method="device_auth",
                cost_class="subscription_or_workspace",
                user_action_required=True,
                exit_code=device.returncode,
            )
        status = self._status(cwd=cwd, timeout=timeout, env=trusted_env)
        return CodexAuthenticationState(
            available=status.returncode == 0,
            method="device_auth",
            cost_class="subscription_or_workspace",
            user_action_required=status.returncode != 0,
            exit_code=status.returncode,
        )


def write_auth_status(path: Path, state: CodexAuthenticationState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
