from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from app.database import harness_learning_repository as learning_repository


RENDER_PROFILE_SKILL_ID = "vedit.longform.render-profile"
BASELINE_RENDER_PROFILE_VERSION = "v1"
CANDIDATE_RENDER_PROFILE_VERSION = "v2"
TIMESTAMP_RENDER_PROFILE_VERSION = "v3"
COMPACT_TEXT_RENDER_PROFILE_VERSION = "v4"
CURRENT_MEDIUM_RENDER_PROFILE_VERSION = "v5"

# Executable, audited bindings. The candidate changes encode speed only; the
# quality target (H.264 / high / CRF mapping), timeline and QA remain unchanged.
_RENDER_PROFILES: dict[str, dict[str, Any]] = {
    "v1": {
        "codec": "h264",
        "quality": "high",
        "prefer_hw": False,
        "hwaccel_decode": False,
        "software_preset": "slow",
    },
    "v2": {
        "codec": "h264",
        "quality": "high",
        "prefer_hw": False,
        "hwaccel_decode": False,
        "software_preset": "medium",
    },
    # v3 changes only timeline placement. Codec, CRF/quality and x264 effort
    # remain identical to v1 so benchmark attribution is isolated.
    "v3": {
        "codec": "h264",
        "quality": "high",
        "prefer_hw": False,
        "hwaccel_decode": False,
        "software_preset": "slow",
        "timeline_placement": "timestamp",
    },
    # v4 keeps v1 encoding quality and adds only graph-level work elimination:
    # timestamp placement plus direct drawtext for static caption/title clips.
    "v4": {
        "codec": "h264",
        "quality": "high",
        "prefer_hw": False,
        "hwaccel_decode": False,
        "software_preset": "slow",
        "timeline_placement": "timestamp",
        "compact_text_overlays": True,
    },
    "v5": {
        "codec": "h264",
        "quality": "high",
        "prefer_hw": False,
        "hwaccel_decode": False,
        "software_preset": "medium",
        "timeline_placement": "timestamp",
        "compact_text_overlays": True,
    },
}


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def render_profile_checksum(version: str) -> str:
    profile = _RENDER_PROFILES.get(version)
    if profile is None:
        raise ValueError(f"unknown render profile version: {version}")
    return sha256(_canonical(profile).encode("utf-8")).hexdigest()


def render_profile_content_ref(version: str) -> str:
    if version not in _RENDER_PROFILES:
        raise ValueError(f"unknown render profile version: {version}")
    return (
        "python:app.services.render_learning_profile_service:"
        f"vedit.longform.render-profile@{version}"
    )


def executable_render_profile(version: str) -> dict[str, Any]:
    profile = _RENDER_PROFILES.get(version)
    if profile is None:
        raise ValueError(f"unknown render profile version: {version}")
    return {
        "skill_id": RENDER_PROFILE_SKILL_ID,
        "version": version,
        "content_ref": render_profile_content_ref(version),
        "checksum": render_profile_checksum(version),
        "options": dict(profile),
    }


def resolve_active_render_profile() -> dict[str, Any]:
    active = learning_repository.get_active_version(
        table="harness_skill_versions",
        identity_field="skill_id",
        identity=RENDER_PROFILE_SKILL_ID,
    )
    if active is None:
        return executable_render_profile(BASELINE_RENDER_PROFILE_VERSION)
    version = str(active["version"])
    executable = executable_render_profile(version)
    if active["content_ref"] != executable["content_ref"]:
        raise PermissionError("active render profile content_ref does not resolve to executable code")
    if active["checksum"] != executable["checksum"]:
        raise PermissionError("active render profile checksum does not match executable code")
    return executable


def bind_active_render_profile(
    render_config: dict[str, Any] | None,
    *,
    routing_id: str | None = None,
    authorization_id: str | None = None,
) -> dict[str, Any]:
    result = dict(render_config or {})
    profile = resolve_active_render_profile()
    result["learning_profile"] = {
        "skill_id": profile["skill_id"],
        "version": profile["version"],
        "content_ref": profile["content_ref"],
        "checksum": profile["checksum"],
        "resolved_by": "deepseek_harness",
        "routing_id": routing_id,
        "authorization_id": authorization_id,
    }
    return result


def resolve_bound_render_options(render_config: dict[str, Any] | None) -> dict[str, Any]:
    render_config = dict(render_config or {})
    binding = render_config.get("learning_profile")
    if binding is None:
        # Legacy RenderJobs retain the exact pre-learning behavior.
        return executable_render_profile(BASELINE_RENDER_PROFILE_VERSION)["options"]
    if not isinstance(binding, dict):
        raise PermissionError("render learning profile binding must be an object")
    if binding.get("resolved_by") != "deepseek_harness":
        raise PermissionError("render learning profile must be resolved by the DeepSeek Harness")
    if binding.get("skill_id") != RENDER_PROFILE_SKILL_ID:
        raise PermissionError("render learning profile skill identity mismatch")
    version = str(binding.get("version") or "")
    executable = executable_render_profile(version)
    for key in ("content_ref", "checksum"):
        if binding.get(key) != executable[key]:
            raise PermissionError(f"render learning profile {key} mismatch")
    return dict(executable["options"])
