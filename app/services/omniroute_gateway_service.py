from __future__ import annotations

from dataclasses import asdict, dataclass
import base64
import json
from pathlib import Path
import time
from typing import Any, Protocol

from app.services.github_actions_artifact_service import GitHubActionsArtifactService
from app.services.github_actions_dispatcher import GitHubActionsDispatcher
from app.services.github_actions_run_watcher import GitHubActionsRunWatcher
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY, GlobalCapabilityRegistry
from app.services.harness_authorization_service import HarnessAuthorization, validate_harness_authorization
from app.services.harness_routing_policy_service import HarnessRoutingDecision, normalize_provider_id
from app.services.zero_cost_policy_service import enforce_zero_cost

OMNIROUTE_VERSION = "3.8.50"
OMNIROUTE_EXECUTOR_BINDING = "app.services.omniroute_gateway_service.execute_omniroute_gateway"
OMNIROUTE_ARTIFACT_NAME = "omniroute-result"

class OmniRouteGatewayError(RuntimeError):
    pass

class OmniRouteGatewayIntegrityError(OmniRouteGatewayError):
    pass

@dataclass(frozen=True)
class OmniRouteTransportResult:
    status: str
    provider: str
    model: str
    text: str
    omniroute_version: str
    runtime_identity: str
    execution_ref: str
    elapsed_seconds: float
    fallback_occurred: bool = False
    retry_count: int = 0
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

@dataclass(frozen=True)
class OmniRouteGatewayEvidence:
    authority: str
    authorization_id: str
    harness_decision_id: str
    execution_id: str
    capability: str
    provider: str
    model: str
    executor: str
    omniroute_version: str
    runtime_identity: str
    execution_ref: str
    status: str
    elapsed_seconds: float
    zero_cost_eligible: bool
    fallback_occurred: bool
    retry_count: int
    result: str | None = None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

class OmniRouteExecutionTransport(Protocol):
    def execute(self, *, prompt: str, provider: str, model: str, execution_id: str) -> OmniRouteTransportResult: ...

class GitHubActionsOmniRouteTransport:
    """Ephemeral standard GitHub runner transport. Never authorizes or routes."""
    def __init__(self, *, repository: str, ref: str, dispatcher: GitHubActionsDispatcher, watcher: GitHubActionsRunWatcher, artifact_service: GitHubActionsArtifactService, workflow: str = "omniroute.yml", artifact_root: str | Path = "runtime/omniroute-artifacts") -> None:
        if not repository or not ref or not workflow:
            raise ValueError("OmniRoute GitHub Actions transport is incomplete")
        self.repository = repository
        self.ref = ref
        self.workflow = workflow
        self.dispatcher = dispatcher
        self.watcher = watcher
        self.artifact_service = artifact_service
        self.artifact_root = Path(artifact_root)

    def execute(self, *, prompt: str, provider: str, model: str, execution_id: str) -> OmniRouteTransportResult:
        if not prompt.strip():
            raise ValueError("OmniRoute prompt is required")
        if provider in {"", "auto"} or model in {"", "auto"} or model.startswith("auto/"):
            raise PermissionError("Autonomous OmniRoute routing is forbidden")
        started = time.monotonic()
        dispatched = self.dispatcher.dispatch(
            repository=self.repository,
            workflow=self.workflow,
            ref=self.ref,
            inputs={
                "mode": "execute",
                "execution_id": execution_id,
                "provider": provider,
                "model": model,
                "prompt_b64": base64.b64encode(prompt.encode()).decode(),
                "zero_cost_operation": "true",
            },
        )
        watched = self.watcher.wait_for_completion(repository=self.repository, run_id=dispatched.run_id)
        if not watched.succeeded:
            raise OmniRouteGatewayError(f"OmniRoute workflow failed run_id={dispatched.run_id} status={watched.status} conclusion={watched.conclusion}")
        output_dir = self.artifact_root / str(dispatched.run_id)
        self.artifact_service.download(repository=self.repository, run_id=dispatched.run_id, artifact_name=OMNIROUTE_ARTIFACT_NAME, output_dir=output_dir)
        files = sorted(output_dir.rglob("result.json"))
        if len(files) != 1:
            raise OmniRouteGatewayError(f"Expected exactly one OmniRoute result.json, found {len(files)}")
        try:
            payload = json.loads(files[0].read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise OmniRouteGatewayError("Invalid OmniRoute result artifact") from exc
        required = {"status", "provider", "model", "text", "omniroute_version", "runtime_identity", "fallback_occurred", "retry_count"}
        if not isinstance(payload, dict) or not required.issubset(payload):
            raise OmniRouteGatewayError("Incomplete OmniRoute result artifact")
        return OmniRouteTransportResult(
            status=str(payload["status"]), provider=str(payload["provider"]), model=str(payload["model"]), text=str(payload["text"]),
            omniroute_version=str(payload["omniroute_version"]), runtime_identity=str(payload["runtime_identity"]), execution_ref=f"github-actions:{dispatched.run_id}",
            elapsed_seconds=float(payload.get("elapsed_seconds") or (time.monotonic() - started)), fallback_occurred=bool(payload["fallback_occurred"]), retry_count=int(payload["retry_count"]),
            warnings=tuple(payload.get("warnings") or ()), errors=tuple(payload.get("errors") or ()),
        )

def _provider_record(provider: str, registry: GlobalCapabilityRegistry):
    normalized = normalize_provider_id(provider)
    matches = [r for r in registry.all() if r.capability_type == "PROVIDER" and r.provider_id and normalize_provider_id(r.provider_id) == normalized]
    if len(matches) != 1:
        raise PermissionError("OmniRoute provider Registry metadata is missing or ambiguous")
    return matches[0]

def execute_omniroute_gateway(*, prompt: str, routing_decision: HarnessRoutingDecision, authorization: HarnessAuthorization | dict[str, Any] | str, transport: OmniRouteExecutionTransport, registry: GlobalCapabilityRegistry = GLOBAL_CAPABILITY_REGISTRY, quota_available: bool | None = True) -> OmniRouteGatewayEvidence:
    if routing_decision.fallback_allowed or routing_decision.fallback_occurred:
        raise PermissionError("OmniRoute fallback is forbidden under Harness governance")
    if not routing_decision.selected_provider or not routing_decision.selected_model:
        raise PermissionError("Harness must select provider and model before OmniRoute")
    if routing_decision.selected_provider_executor_binding != OMNIROUTE_EXECUTOR_BINDING:
        raise PermissionError("OmniRoute executor binding mismatch")
    if routing_decision.selected_provider == "auto" or routing_decision.selected_model.startswith("auto"):
        raise PermissionError("OmniRoute autonomous routing is forbidden")
    if routing_decision.policy_metadata.get("zero_cost_operation") is not True:
        raise PermissionError("ZERO_COST_OPERATION must be enforced before OmniRoute")
    provider_record = _provider_record(routing_decision.selected_provider, registry)
    if provider_record.model_id != routing_decision.selected_model:
        raise PermissionError("Harness-selected model does not match Registry provider model")
    assessment = enforce_zero_cost(provider_record.cost_class, quota_available=quota_available)
    resolved = validate_harness_authorization(
        authorization,
        expected_action=routing_decision.authorized_action,
        expected_subject=f"provider:{normalize_provider_id(routing_decision.selected_provider)}",
    )
    result = transport.execute(prompt=prompt, provider=normalize_provider_id(routing_decision.selected_provider), model=routing_decision.selected_model, execution_id=resolved.execution_id)
    if result.status != "EXECUTED":
        raise OmniRouteGatewayError("OmniRoute execution did not succeed")
    if normalize_provider_id(result.provider) != normalize_provider_id(routing_decision.selected_provider):
        raise OmniRouteGatewayIntegrityError("OmniRoute provider identity mismatch")
    if result.model != routing_decision.selected_model:
        raise OmniRouteGatewayIntegrityError("OmniRoute model identity mismatch")
    if result.omniroute_version != OMNIROUTE_VERSION:
        raise OmniRouteGatewayIntegrityError("OmniRoute version mismatch")
    if result.fallback_occurred:
        raise OmniRouteGatewayIntegrityError("OmniRoute reported unauthorized fallback")
    return OmniRouteGatewayEvidence(
        authority=resolved.authority, authorization_id=resolved.authorization_id, harness_decision_id=resolved.harness_decision_id, execution_id=resolved.execution_id,
        capability=routing_decision.selected_capability_id, provider=normalize_provider_id(routing_decision.selected_provider), model=routing_decision.selected_model,
        executor=OMNIROUTE_EXECUTOR_BINDING, omniroute_version=result.omniroute_version, runtime_identity=result.runtime_identity, execution_ref=result.execution_ref,
        status=result.status, elapsed_seconds=result.elapsed_seconds, zero_cost_eligible=assessment.eligible, fallback_occurred=False, retry_count=result.retry_count,
        result=result.text, warnings=result.warnings, errors=result.errors,
    )
