from __future__ import annotations

import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any

from app.services.ai_provider import AIProviderError, AIResponse
from app.services.github_actions_artifact_service import GitHubActionsArtifactService
from app.services.github_actions_command_runner import run_github_actions_command
from app.services.github_actions_dispatcher import GitHubActionsDispatcher
from app.services.github_actions_run_tracker import GitHubActionsRunTracker
from app.services.github_actions_run_watcher import GitHubActionsRunWatcher


OPENCODE_NATIVE_ARTIFACT_NAME = "opencode-native-result"
OPENCODE_NATIVE_WORKFLOW = "opencode-native-ai.yml"
OPENCODE_NATIVE_EXECUTOR_BINDING = (
    "app.services.opencode_native_ai_provider.OpenCodeNativeAIProvider"
)

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_OPENCODE_HANDOFF_PREFIX = "opencode-handoff"


def _immutable_dispatch_ref(
    *,
    repository: str,
    configured_ref: str,
    command_runner,
) -> tuple[str, str | None]:
    """Resolve one immutable workflow_dispatch tag to the exact parent GitHub SHA.

    Outside GitHub Actions, preserve the explicitly configured ref for local/unit
    callers. Inside Actions, never dispatch a semantic child on a moving branch.
    """
    source_sha = str(os.getenv("GITHUB_SHA") or "").strip().lower()
    in_actions = str(os.getenv("GITHUB_ACTIONS") or "").strip().lower() == "true"
    if not in_actions:
        return configured_ref, source_sha if _GIT_SHA_RE.fullmatch(source_sha) else None
    if not _GIT_SHA_RE.fullmatch(source_sha):
        raise OpenCodeNativeAIProviderError(
            "GitHub-hosted OpenCode execution requires an exact parent source SHA",
            details={"failure_code": "missing_parent_source_sha"},
        )

    tag = f"{_OPENCODE_HANDOFF_PREFIX}-{source_sha}"
    endpoint = f"repos/{repository}/git/ref/tags/{tag}"

    def read_target() -> str:
        value = command_runner([
            "gh", "api", endpoint, "--jq", ".object.sha",
        ]).strip().lower()
        if not _GIT_SHA_RE.fullmatch(value):
            raise OpenCodeNativeAIProviderError(
                "OpenCode handoff tag returned an invalid Git object SHA",
                details={"failure_code": "invalid_handoff_tag_target"},
            )
        return value

    try:
        target = read_target()
    except RuntimeError as exc:
        message = str(exc).lower()
        if "404" not in message and "not found" not in message and "does not exist" not in message:
            raise OpenCodeNativeAIProviderError(
                "Unable to verify OpenCode immutable handoff tag",
                details={"failure_code": "handoff_tag_lookup_failed"},
            ) from exc
        try:
            command_runner([
                "gh", "api", "--method", "POST",
                f"repos/{repository}/git/refs",
                "-f", f"ref=refs/tags/{tag}",
                "-f", f"sha={source_sha}",
                "--jq", ".object.sha",
            ])
        except RuntimeError as create_exc:
            # Parallel semantic calls may race to create the same commit tag.
            race = str(create_exc).lower()
            if "422" not in race and "already exists" not in race and "reference exists" not in race:
                raise OpenCodeNativeAIProviderError(
                    "Unable to create OpenCode immutable handoff tag",
                    details={"failure_code": "handoff_tag_create_failed"},
                ) from create_exc
        target = read_target()

    if target != source_sha:
        raise OpenCodeNativeAIProviderError(
            "OpenCode immutable handoff tag does not match the parent source SHA",
            details={"failure_code": "handoff_tag_sha_mismatch"},
        )
    return tag, source_sha



class OpenCodeNativeAIProviderError(AIProviderError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.safe_message = message
        self.details = dict(details or {})
        self.status_code = self.details.get("http_status")
        self.retryable = bool(self.details.get("retryable", False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": "opencode",
            "model": self.details.get("canonical_model"),
            "code": self.details.get("failure_code", "opencode_native_failure"),
            "status_code": self.details.get("http_status"),
            "retryable": self.retryable,
            "message": self.safe_message,
            "error_type": type(self).__name__,
            "execution_ref": self.details.get("execution_ref"),
            "run_id": self.details.get("run_id"),
            "workflow_status": self.details.get("status"),
            "workflow_conclusion": self.details.get("conclusion"),
            "exit_code": self.details.get("exit_code"),
            "log_sha256": self.details.get("log_sha256"),
            "retry_count": int(self.details.get("retry_count") or 0),
            "profile_version": self.details.get("profile_version"),
            "profile_content_ref": self.details.get("profile_content_ref"),
        }


def _sanitize_failed_log(log_text: str) -> dict[str, Any]:
    text = str(log_text or "")
    exit_codes = [
        int(value)
        for value in re.findall(r"exit code\s+(\d+)", text, flags=re.IGNORECASE)
    ]
    error_codes = []
    for pattern in (
        r"error_code[=:]\s*([A-Za-z0-9_.-]+)",
        r"OPENCODE_NATIVE_ERROR[=:]\s*([A-Za-z0-9_.-]+)",
    ):
        error_codes.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    result: dict[str, Any] = {
        "log_sha256": sha256(text.encode("utf-8")).hexdigest(),
        "failure_code": (
            error_codes[-1] if error_codes else "opencode_native_workflow_failure"
        ),
    }
    if exit_codes:
        result["exit_code"] = exit_codes[-1]
    return result


class OpenCodeNativeAIProvider:
    """Official OpenCode CLI executed on a bounded GitHub Actions runner."""

    def __init__(
        self,
        *,
        routing_decision,
        authorization,
        profile: dict[str, Any],
        repository: str | None = None,
        ref: str | None = None,
    ) -> None:
        self.routing_decision = routing_decision
        self.authorization = authorization
        self.profile = dict(profile)
        self.options = dict(profile.get("options") or {})
        self.executor_binding = OPENCODE_NATIVE_EXECUTOR_BINDING
        self.profile_version = str(profile["version"])
        self.profile_content_ref = str(profile["content_ref"])
        self.profile_checksum = str(profile["checksum"])
        self.repository = (
            repository
            or os.getenv("BR_OPENCODE_NATIVE_REPOSITORY")
            or os.getenv("GITHUB_ACTIONS_REPOSITORY")
            or "zenindiones-maker/BR-no-GTA"
        ).strip()
        self.ref = (
            ref
            or os.getenv("BR_OPENCODE_NATIVE_REF")
            or os.getenv("BR_OMNIROUTE_REF")
            or os.getenv("GITHUB_ACTIONS_RENDER_REF")
            or "main"
        ).strip()
        if not self.repository or not self.ref:
            raise ValueError("OpenCode native GitHub repository/ref are required")
        if self.options.get("executor_kind") != "official_opencode_cli_github_actions":
            raise PermissionError("OpenCode native provider received a non-native profile")
        if routing_decision.selected_provider != "opencode":
            raise PermissionError("OpenCode native provider identity mismatch")
        if routing_decision.selected_model != self.options.get("canonical_model"):
            raise PermissionError("OpenCode native canonical model mismatch")

        command_runner = run_github_actions_command
        dispatcher = GitHubActionsDispatcher(command_runner)
        tracker = GitHubActionsRunTracker(command_runner)
        watcher = GitHubActionsRunWatcher(
            tracker,
            poll_interval=float(os.getenv("BR_OPENCODE_NATIVE_POLL_INTERVAL", "5")),
            timeout=float(os.getenv("BR_OPENCODE_NATIVE_RUN_TIMEOUT", "900")),
        )
        artifacts = GitHubActionsArtifactService(command_runner)
        self.command_runner = command_runner
        self.dispatcher = dispatcher
        self.watcher = watcher
        self.artifacts = artifacts
        self.artifact_root = Path(
            os.getenv(
                "BR_OPENCODE_NATIVE_ARTIFACT_ROOT",
                "runtime/opencode-native-artifacts",
            )
        )

    def generate(self, prompt: str) -> AIResponse:
        if not isinstance(prompt, str) or not prompt.strip():
            raise AIProviderError("OpenCode prompt must be non-empty")

        canonical_model = str(self.options["canonical_model"])
        executor_model = str(self.options["executor_model"])
        cli_version = str(self.options["cli_version"])
        workflow = str(self.options.get("workflow") or OPENCODE_NATIVE_WORKFLOW)
        dispatch_ref, source_sha = _immutable_dispatch_ref(
            repository=self.repository,
            configured_ref=self.ref,
            command_runner=self.command_runner,
        )
        dispatched = self.dispatcher.dispatch(
            repository=self.repository,
            workflow=workflow,
            ref=dispatch_ref,
            inputs={
                "mode": "opencode_native",
                "execution_id": self.authorization.execution_id,
                "provider": "opencode",
                "model": canonical_model,
                "prompt_b64": base64.b64encode(prompt.encode("utf-8")).decode("ascii"),
                "zero_cost_operation": "true",
                "expected_source_sha": source_sha or "",
            },
        )
        watched = self.watcher.wait_for_completion(
            repository=self.repository,
            run_id=dispatched.run_id,
        )
        if not watched.succeeded:
            try:
                failed_log = self.command_runner([
                    "gh",
                    "run",
                    "view",
                    str(dispatched.run_id),
                    "--repo",
                    self.repository,
                    "--log-failed",
                ])
            except Exception:
                failed_log = ""
            details = {
                "execution_ref": f"github-actions:{dispatched.run_id}",
                "run_id": dispatched.run_id,
                "status": watched.status,
                "conclusion": watched.conclusion,
                "canonical_model": canonical_model,
                "executor_model": executor_model,
                "profile_version": self.profile_version,
                "profile_content_ref": self.profile_content_ref,
                "retry_count": 0,
                **_sanitize_failed_log(failed_log),
            }
            raise OpenCodeNativeAIProviderError(
                "Governed OpenCode native execution failed",
                details=details,
            )

        output_dir = self.artifact_root / str(dispatched.run_id)
        self.artifacts.download(
            repository=self.repository,
            run_id=dispatched.run_id,
            artifact_name=OPENCODE_NATIVE_ARTIFACT_NAME,
            output_dir=output_dir,
        )
        files = sorted(output_dir.rglob("result.json"))
        if len(files) != 1:
            raise OpenCodeNativeAIProviderError(
                "OpenCode native result artifact is missing or ambiguous",
                details={
                    "execution_ref": f"github-actions:{dispatched.run_id}",
                    "run_id": dispatched.run_id,
                    "canonical_model": canonical_model,
                    "profile_version": self.profile_version,
                    "profile_content_ref": self.profile_content_ref,
                    "failure_code": "invalid_result_artifact",
                },
            )
        try:
            payload = json.loads(files[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OpenCodeNativeAIProviderError(
                "OpenCode native result artifact is invalid",
                details={
                    "execution_ref": f"github-actions:{dispatched.run_id}",
                    "run_id": dispatched.run_id,
                    "canonical_model": canonical_model,
                    "profile_version": self.profile_version,
                    "profile_content_ref": self.profile_content_ref,
                    "failure_code": "invalid_result_json",
                },
            ) from exc

        required = {
            "status",
            "provider",
            "canonical_model",
            "executor_model",
            "text",
            "cli_version",
            "runtime_identity",
            "elapsed_seconds",
            "fallback_occurred",
            "retry_count",
        }
        if not isinstance(payload, dict) or not required.issubset(payload):
            raise OpenCodeNativeAIProviderError(
                "OpenCode native result is incomplete",
                details={
                    "execution_ref": f"github-actions:{dispatched.run_id}",
                    "run_id": dispatched.run_id,
                    "canonical_model": canonical_model,
                    "profile_version": self.profile_version,
                    "profile_content_ref": self.profile_content_ref,
                    "failure_code": "incomplete_result",
                },
            )
        if payload["status"] != "EXECUTED":
            raise OpenCodeNativeAIProviderError(
                "OpenCode native result did not succeed",
                details={
                    "execution_ref": f"github-actions:{dispatched.run_id}",
                    "run_id": dispatched.run_id,
                    "canonical_model": canonical_model,
                    "profile_version": self.profile_version,
                    "profile_content_ref": self.profile_content_ref,
                    "failure_code": "non_executed_result",
                },
            )
        if payload["provider"] != "opencode":
            raise PermissionError("OpenCode native provider identity mismatch")
        if payload["canonical_model"] != canonical_model:
            raise PermissionError("OpenCode native canonical model mismatch")
        if payload["executor_model"] != executor_model:
            raise PermissionError("OpenCode native executor model mismatch")
        if payload["cli_version"] != cli_version:
            raise PermissionError("OpenCode native CLI version mismatch")
        if payload["fallback_occurred"] is not False:
            raise PermissionError("OpenCode native executor reported fallback")
        text = str(payload["text"] or "").strip()
        if not text:
            raise OpenCodeNativeAIProviderError(
                "OpenCode native executor returned no usable text",
                details={
                    "execution_ref": f"github-actions:{dispatched.run_id}",
                    "run_id": dispatched.run_id,
                    "canonical_model": canonical_model,
                    "profile_version": self.profile_version,
                    "profile_content_ref": self.profile_content_ref,
                    "failure_code": "empty_result",
                    "retryable": True,
                },
            )

        return AIResponse(
            text=text,
            provider="opencode",
            model=canonical_model,
            finish_reason="stop",
        )
