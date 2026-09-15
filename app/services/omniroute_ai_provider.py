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
        except (OmniRouteGatewayError, PermissionError, ValueError) as exc:
            raise AIProviderError("Governed zero-cost OmniRoute execution failed") from exc
        text = evidence.result or ""
        if not text.strip():
            raise AIProviderError("Governed zero-cost OmniRoute returned an empty result")
        return AIResponse(
            text=text,
            provider=evidence.provider,
            model=evidence.model,
            finish_reason="stop",
        )
