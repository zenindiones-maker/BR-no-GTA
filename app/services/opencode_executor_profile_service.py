from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from app.database import harness_learning_repository as learning_repository
from app.services.ai_provider import AIProviderError, AIResponse


OPENCODE_EXECUTOR_SKILL_ID = "ai.reasoning.opencode-executor-profile"
BASELINE_OPENCODE_EXECUTOR_VERSION = "v1"
CANDIDATE_OPENCODE_EXECUTOR_VERSION = "v2"
SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION = "v3"
OPENCODE_PROFILE_RESOLVER_BINDING = (
    "app.services.opencode_executor_profile_service."
    "create_opencode_provider_for_active_profile"
)

_PROFILES: dict[str, dict[str, Any]] = {
    "v1": {
        "executor_kind": "omniroute_http",
        "executor_binding": "app.services.omniroute_gateway_service.execute_omniroute_gateway",
        "canonical_model": "oc/big-pickle",
        "executor_model": "oc/big-pickle",
        "status": "BLOCKED_OBSERVED_403",
        "evidence_run_id": 35340487375,
    },
    "v2": {
        "executor_kind": "official_opencode_cli_github_actions",
        "executor_binding": (
            "app.services.opencode_native_ai_provider.OpenCodeNativeAIProvider"
        ),
        "canonical_model": "oc/big-pickle",
        "executor_model": "opencode/big-pickle",
        "workflow": "omniroute.yml",
        "cli_version": "2.0.8",
        "status": "PROMOTED",
        "evidence_run_id": 35450516329,
    },
    "v3": {
        "executor_kind": "official_opencode_cli_github_actions",
        "executor_binding": (
            "app.services.opencode_native_ai_provider.OpenCodeNativeAIProvider"
        ),
        "canonical_model": "oc/big-pickle",
        "executor_model": "opencode/big-pickle",
        "workflow": "omniroute.yml",
        "cli_version": "2.0.8",
        "semantic_profile": "opencode-semantic-text-v3",
        "semantic_agent": "semantic-text",
        "semantic_steps": 1,
        "semantic_contract": "SEMANTIC_TEXT_ONLY",
        "status": "CANDIDATE_ROOT_CAUSE_FIX",
        "root_cause_evidence_run_id": 35537494044,
        "root_cause_artifact_id": 10612603412,
    },
}


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def opencode_executor_profile_checksum(version: str) -> str:
    profile = _PROFILES.get(version)
    if profile is None:
        raise ValueError(f"unknown OpenCode executor profile version: {version}")
    return sha256(_canonical(profile).encode("utf-8")).hexdigest()


def opencode_executor_profile_content_ref(version: str) -> str:
    if version not in _PROFILES:
        raise ValueError(f"unknown OpenCode executor profile version: {version}")
    return (
        "python:app.services.opencode_executor_profile_service:"
        f"{OPENCODE_EXECUTOR_SKILL_ID}@{version}"
    )


def executable_opencode_executor_profile(version: str) -> dict[str, Any]:
    profile = _PROFILES.get(version)
    if profile is None:
        raise ValueError(f"unknown OpenCode executor profile version: {version}")
    return {
        "skill_id": OPENCODE_EXECUTOR_SKILL_ID,
        "version": version,
        "content_ref": opencode_executor_profile_content_ref(version),
        "checksum": opencode_executor_profile_checksum(version),
        "options": dict(profile),
    }


def resolve_active_opencode_executor_profile() -> dict[str, Any]:
    active = learning_repository.get_active_version(
        table="harness_skill_versions",
        identity_field="skill_id",
        identity=OPENCODE_EXECUTOR_SKILL_ID,
    )
    if active is None:
        return executable_opencode_executor_profile(
            BASELINE_OPENCODE_EXECUTOR_VERSION
        )
    version = str(active["version"])
    executable = executable_opencode_executor_profile(version)
    if active["content_ref"] != executable["content_ref"]:
        raise PermissionError(
            "active OpenCode executor profile content_ref does not resolve to executable code"
        )
    if active["checksum"] != executable["checksum"]:
        raise PermissionError(
            "active OpenCode executor profile checksum does not match executable code"
        )
    return executable


class OpenCodeBlockedBaselineError(AIProviderError):
    def __init__(self, profile: dict[str, Any]):
        super().__init__(
            "OpenCode OmniRoute baseline is blocked by observed upstream policy"
        )
        self.profile = profile
        self.safe_message = str(self)
        self.retryable = False
        self.status_code = 403

    def to_dict(self) -> dict[str, Any]:
        options = dict(self.profile["options"])
        return {
            "provider": "opencode",
            "model": options["canonical_model"],
            "code": "baseline_executor_disproven",
            "status_code": 403,
            "retryable": False,
            "message": self.safe_message,
            "error_type": type(self).__name__,
            "observed_failure_run_id": options["evidence_run_id"],
            "profile_skill_id": self.profile["skill_id"],
            "profile_version": self.profile["version"],
            "profile_content_ref": self.profile["content_ref"],
            "profile_checksum": self.profile["checksum"],
            "executor_binding": options["executor_binding"],
        }


class OpenCodeDisprovenSemanticProfileError(AIProviderError):
    def __init__(self, profile: dict[str, Any]):
        super().__init__(
            "OpenCode semantic profile v2 is blocked by observed semantic tool use"
        )
        self.profile = profile
        self.safe_message = str(self)
        self.retryable = False

    def to_dict(self) -> dict[str, Any]:
        options = dict(self.profile["options"])
        return {
            "provider": "opencode",
            "model": options["canonical_model"],
            "code": "semantic_tools_used",
            "retryable": False,
            "message": self.safe_message,
            "error_type": type(self).__name__,
            "observed_failure_run_id": 35537494044,
            "observed_failure_artifact_id": 10612603412,
            "profile_skill_id": self.profile["skill_id"],
            "profile_version": self.profile["version"],
            "profile_content_ref": self.profile["content_ref"],
            "profile_checksum": self.profile["checksum"],
            "executor_binding": options["executor_binding"],
            "failure_pattern": "opencode_semantic_tools_used",
        }


class _DisprovenSemanticProvider:
    def __init__(self, profile: dict[str, Any]):
        self.profile = profile
        self.executor_binding = profile["options"]["executor_binding"]
        self.profile_version = profile["version"]
        self.profile_content_ref = profile["content_ref"]
        self.profile_checksum = profile["checksum"]

    def generate(self, prompt: str) -> AIResponse:
        if not isinstance(prompt, str) or not prompt.strip():
            raise AIProviderError("OpenCode prompt must be non-empty")
        raise OpenCodeDisprovenSemanticProfileError(self.profile)


class _BlockedBaselineProvider:
    def __init__(self, profile: dict[str, Any]):
        self.profile = profile
        self.executor_binding = profile["options"]["executor_binding"]
        self.profile_version = profile["version"]
        self.profile_content_ref = profile["content_ref"]
        self.profile_checksum = profile["checksum"]

    def generate(self, prompt: str) -> AIResponse:
        if not isinstance(prompt, str) or not prompt.strip():
            raise AIProviderError("OpenCode prompt must be non-empty")
        raise OpenCodeBlockedBaselineError(self.profile)


def create_opencode_provider_for_active_profile(
    *,
    routing_decision,
    authorization,
):
    profile = resolve_active_opencode_executor_profile()
    options = dict(profile["options"])
    if routing_decision.selected_provider != "opencode":
        raise PermissionError("OpenCode executor profile received another provider")
    if routing_decision.selected_model != options["canonical_model"]:
        raise PermissionError("OpenCode executor profile model identity mismatch")

    if profile["version"] == BASELINE_OPENCODE_EXECUTOR_VERSION:
        return _BlockedBaselineProvider(profile)
    if profile["version"] == CANDIDATE_OPENCODE_EXECUTOR_VERSION:
        return _DisprovenSemanticProvider(profile)
    if profile["version"] == SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION:
        from app.services.opencode_native_ai_provider import OpenCodeNativeAIProvider

        return OpenCodeNativeAIProvider(
            routing_decision=routing_decision,
            authorization=authorization,
            profile=profile,
        )
    raise PermissionError("unrecognized promoted OpenCode executor profile")
