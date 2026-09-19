from __future__ import annotations

import os
from urllib.parse import urlparse
from typing import Any

from app.services.github_actions_command_runner import run_github_actions_command
from app.services.github_actions_dispatcher import GitHubActionsDispatcher


MEDIA_ANALYSIS_CLOUD_CAPABILITY_ID = "media.analysis.cloud"
MEDIA_ANALYSIS_CLOUD_EXECUTOR_BINDING = (
    "app.services.media_analysis_cloud_service.execute_media_analysis_cloud_capability"
)
MEDIA_ANALYSIS_WORKFLOW = "media-worker.yml"


def _public_https(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("media.analysis.cloud requires source_url")
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("source_url must use public HTTPS")
    host = parsed.hostname.casefold().rstrip(".")
    if host == "localhost" or host.endswith((".local", ".internal")):
        raise ValueError("source_url host is not public")
    return url


def execute_media_analysis_cloud_capability(
    capability: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch the fixed heavy MediaKnowledge/Whisper workflow.

    The caller cannot choose an arbitrary workflow or shell command. GitHub Actions
    remains the heavy executor and the result is a run identity to be reconciled
    through the existing artifact import boundary.
    """
    if getattr(capability, "capability_id", None) != MEDIA_ANALYSIS_CLOUD_CAPABILITY_ID:
        raise PermissionError("media analysis cloud capability mismatch")
    if getattr(capability, "executor_binding", None) != MEDIA_ANALYSIS_CLOUD_EXECUTOR_BINDING:
        raise PermissionError("media analysis cloud executor binding mismatch")

    source_url = _public_https(payload.get("source_url"))
    source_name = payload.get("source_name", "gta6-media")
    if not isinstance(source_name, str) or not source_name.strip():
        raise ValueError("source_name must be non-empty")
    source_name = source_name.strip()
    if len(source_name) > 120:
        raise ValueError("source_name exceeds bounded length")

    repository = (
        os.getenv("GITHUB_ACTIONS_REPOSITORY")
        or os.getenv("GITHUB_REPOSITORY")
        or "zenindiones-maker/BR-no-GTA"
    ).strip()
    ref = (
        os.getenv("GITHUB_ACTIONS_RENDER_REF")
        or os.getenv("GITHUB_REF_NAME")
        or "work/gate6f-analytics-learning"
    ).strip()
    test_only = bool(payload.get("test_only", False))

    dispatcher = GitHubActionsDispatcher(run_github_actions_command)
    dispatch = dispatcher.dispatch(
        repository=repository,
        workflow=MEDIA_ANALYSIS_WORKFLOW,
        ref=ref,
        inputs={
            "source_url": source_url,
            "source_name": source_name,
            "test_only": "true" if test_only else "false",
        },
    )
    return {
        "status": "DISPATCHED",
        "repository": dispatch.repository,
        "workflow": dispatch.workflow,
        "ref": dispatch.ref,
        "run_id": dispatch.run_id,
        "source_url": source_url,
        "source_name": source_name,
        "test_only": test_only,
        "artifact_contract": "media-knowledge + optional speech-analysis",
    }
