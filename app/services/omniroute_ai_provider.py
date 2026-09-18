from __future__ import annotations

import os
from pathlib import Path

from app.services.ai_provider import AIProviderError, AIResponse
from app.services.github_actions_artifact_service import GitHubActionsArtifactService
from app.services.github_actions_command_runner import run_github_actions_command
from app.services.github_actions_dispatcher import GitHubActionsDispatcher
from app.services.github_actions_run_tracker import GitHubActionsRunTracker
from app.services.github_actions_run_watcher import GitHubActionsRunWatcher
from app.services.harness_authorization_service import HarnessAuthorization
from app.services.harness_routing_policy_service import HarnessRoutingDecision
from app.services.omniroute_gateway_service import (
    GitHubActionsOmniRouteTransport,
    OmniRouteGatewayError,
    execute_omniroute_gateway,
)


class OmniRouteAIProviderError(AIProviderError):
    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.safe_message = message
        self.details = dict(details or {})
        self.status_code = self.details.get("http_status")
        self.retryable = bool(self.details.get("retryable", False))

    def to_dict(self) -> dict:
        return {
            "provider": self.details.get("provider", "opencode"),
            "model": self.details.get("model"),
            "code": self.details.get("failure_code", "omniroute_failure"),
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
        }


class OmniRouteAIProvider:
    """AIProvider adapter over the bounded zero-cost OmniRoute GitHub executor.

    The Harness has already selected provider/model/executor and issued the
    provider-scoped authorization before this adapter is constructed. This
    class cannot route, authorize, fallback, publish, schedule, or mutate the
    control-plane database.
    """

    def __init__(
        self,
        *,
        routing_decision: HarnessRoutingDecision,
        authorization: HarnessAuthorization,
        repository: str | None = None,
        ref: str | None = None,
    ) -> None:
        self.routing_decision = routing_decision
        self.authorization = authorization
        self.repository = (
            repository
            or os.getenv("BR_OMNIROUTE_REPOSITORY")
            or os.getenv("GITHUB_ACTIONS_REPOSITORY")
            or "zenindiones-maker/BR-no-GTA"
        ).strip()
        self.ref = (
            ref
            or os.getenv("BR_OMNIROUTE_REF")
            or os.getenv("GITHUB_ACTIONS_RENDER_REF")
            or "main"
        ).strip()
        if not self.repository or not self.ref:
            raise ValueError("OmniRoute GitHub Actions repository/ref are required")

        dispatcher = GitHubActionsDispatcher(run_github_actions_command)
        tracker = GitHubActionsRunTracker(run_github_actions_command)
        watcher = GitHubActionsRunWatcher(
            tracker,
            poll_interval=float(os.getenv("BR_OMNIROUTE_POLL_INTERVAL", "5")),
            timeout=float(os.getenv("BR_OMNIROUTE_RUN_TIMEOUT", "900")),
        )
        artifacts = GitHubActionsArtifactService(run_github_actions_command)
        self.transport = GitHubActionsOmniRouteTransport(
            repository=self.repository,
            ref=self.ref,
            dispatcher=dispatcher,
            watcher=watcher,
            artifact_service=artifacts,
            command_runner=run_github_actions_command,
            artifact_root=Path(
                os.getenv(
                    "BR_OMNIROUTE_ARTIFACT_ROOT",
                    "runtime/omniroute-artifacts",
                )
            ),
        )

    def generate(self, prompt: str) -> AIResponse:
        if not isinstance(prompt, str) or not prompt.strip():
            raise AIProviderError("OmniRoute prompt must be non-empty")
        try:
            evidence = execute_omniroute_gateway(
                prompt=prompt,
                routing_decision=self.routing_decision,
                authorization=self.authorization,
                transport=self.transport,
                quota_available=True,
            )
        except OmniRouteGatewayError as exc:
            raise OmniRouteAIProviderError(
                "Governed zero-cost OmniRoute execution failed",
                details=exc.to_dict(),
            ) from exc
        except (PermissionError, ValueError) as exc:
            raise OmniRouteAIProviderError(
                "Governed zero-cost OmniRoute execution was rejected",
                details={
                    "provider": self.routing_decision.selected_provider,
                    "model": self.routing_decision.selected_model,
                    "failure_code": "governance_rejection",
                    "retryable": False,
                    "error_type": type(exc).__name__,
                },
            ) from exc
        text = evidence.result or ""
        if not text.strip():
            raise OmniRouteAIProviderError(
                "Governed zero-cost OmniRoute returned an empty result",
                details={
                    "provider": evidence.provider,
                    "model": evidence.model,
                    "failure_code": "empty_result",
                    "execution_ref": evidence.execution_ref,
                    "retry_count": evidence.retry_count,
                    "retryable": True,
                },
            )
        return AIResponse(
            text=text,
            provider=evidence.provider,
            model=evidence.model,
            finish_reason="stop",
        )
