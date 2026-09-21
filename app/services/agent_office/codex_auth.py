from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request

from app.services.agent_office.codex_bounded_worker import codex_sanitized_environment


Runner = Callable[..., subprocess.CompletedProcess[str]]

_DEVICE_URL_RE = re.compile(r"https://[^\s]+/codex/device")
_ANSI_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")
_DEVICE_CODE_RE = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4,8}\b")


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

    def _deliver_device_auth_private(
        self,
        *,
        verification_url: str,
        user_code: str,
    ) -> int:
        token = self._environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        paired_user_id = self._environ.get("TELEGRAM_ALLOWED_USER_ID", "").strip()
        chat_id = paired_user_id
        destination_class = "paired_user_dm"
        run_id = self._environ.get("GITHUB_RUN_ID", "").strip()
        if not token or not chat_id or not run_id:
            raise RuntimeError("private Telegram device-auth delivery is not configured")
        endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
        message = (
            "BR no GTA — Codex device auth\n"
            f"VERIFICATION_URL={verification_url}\n"
            f"USER_CODE={user_code}\n"
            f"RUN_ID={run_id}\n\n"
            "Código temporário de uso único. Autorize agora; o mesmo runner está aguardando."
        )
        request = urllib.request.Request(
            endpoint,
            data=urllib.parse.urlencode(
                {"chat_id": chat_id, "text": message, "disable_web_page_preview": "true"}
            ).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"private Telegram device-auth delivery failed with HTTP {exc.code}"
            ) from None
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RuntimeError("private Telegram device-auth delivery was rejected")
        result = payload.get("result")
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if not isinstance(message_id, int) or message_id <= 0:
            raise RuntimeError("private Telegram device-auth delivery returned no message identity")
        evidence_path = Path(
            self._environ.get(
                "CODEX_AUTH_DELIVERY_EVIDENCE_FILE",
                "artifacts/delegated-autonomy/device-auth-delivery.json",
            )
        )
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "destination_configured": True,
                    "destination_class": destination_class,
                    "delivery_accepted": True,
                    "telegram_message_id": message_id,
                    "user_code_recorded": False,
                    "credential_recorded": False,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return message_id

    def _device_auth_private(
        self,
        *,
        cwd: Path,
        timeout: float,
        env: Mapping[str, str],
    ) -> int:
        process = subprocess.Popen(
            ["codex", "login", "--device-auth"],
            cwd=cwd,
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if process.stdout is None:
            process.kill()
            raise RuntimeError("Codex device-auth output stream is unavailable")

        verification_url = ""
        user_code = ""
        delivered = False
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    process.kill()
                    return 124
                line = process.stdout.readline()
                if not line:
                    time.sleep(0.05)
                    continue
                clean_line = _ANSI_SGR_RE.sub("", line)
                if not verification_url:
                    match = _DEVICE_URL_RE.search(clean_line)
                    if match:
                        verification_url = match.group(0).rstrip(".,;)")
                if not user_code:
                    match = _DEVICE_CODE_RE.search(clean_line)
                    if match:
                        user_code = match.group(0)
                if verification_url and user_code and not delivered:
                    try:
                        message_id = self._deliver_device_auth_private(
                            verification_url=verification_url,
                            user_code=user_code,
                        )
                    except Exception:
                        print("TELEGRAM_DESTINATION_CONFIGURED=YES", flush=True)
                        print("TELEGRAM_DELIVERY_ACCEPTED=NO", flush=True)
                        raise
                    delivered = True
                    print("TELEGRAM_DESTINATION_CONFIGURED=YES", flush=True)
                    print("AUTH_DELIVERY_SURFACE=PAIRED_USER_DM", flush=True)
                    print("TELEGRAM_DELIVERY_ACCEPTED=YES", flush=True)
                    print(f"TELEGRAM_MESSAGE_ID={message_id}", flush=True)
                    print("DEVICE_AUTH_REVIEW_GROUP_FALLBACK=NO", flush=True)
                    print("WAITING_FOR_USER_AUTH=YES", flush=True)
            return int(process.returncode or 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

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
        private_delivery = bool(
            source.get("TELEGRAM_BOT_TOKEN", "").strip()
            and source.get("TELEGRAM_ALLOWED_USER_ID", "").strip()
            and source.get("GITHUB_RUN_ID", "").strip()
        )
        if private_delivery:
            device_returncode = self._device_auth_private(
                cwd=cwd,
                timeout=timeout,
                env=trusted_env,
            )
        else:
            print("AUTH_DELIVERY_SURFACE=NONE", flush=True)
            print("TELEGRAM_DELIVERY_ACCEPTED=NO", flush=True)
            print("DEVICE_AUTH_REVIEW_GROUP_FALLBACK=NO", flush=True)
            return CodexAuthenticationState(
                available=False,
                method="device_auth",
                cost_class="subscription_or_workspace",
                user_action_required=True,
                exit_code=4,
            )
        if device_returncode != 0:
            return CodexAuthenticationState(
                available=False,
                method="device_auth",
                cost_class="subscription_or_workspace",
                user_action_required=True,
                exit_code=device_returncode,
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
