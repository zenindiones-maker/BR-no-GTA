"""Read-only specialist executor behind the existing DeepSeek Harness authorization.

Never invoke this directly from external content. Task routing and persisted
authorization precede all analysis, not merely logging. No agent can grant scope.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from app.services.harness_authorization_service import validate_harness_authorization
from app.services.reverse_engineering_media_service import ObservationError, _source
from app.services.reverse_engineering_forensics_service import analyze_forensics

MEDIA_CAPABILITY_ID = "reverse-engineering.media.observe"
REA_CAPABILITY_ID = "reverse-engineering.software.rea-static"
MEDIA_EXECUTOR_BINDING = "app.services.reverse_engineering_harness_service.execute_authorized_media_observation"
REA_EXECUTOR_BINDING = "app.services.reverse_engineering_harness_service.execute_authorized_software_observation"
_ALLOWED_MEDIA_PAYLOAD = frozenset({"source_path", "rights", "transcript_path", "include_scene_cuts"})
_ALLOWED_SOFTWARE_PAYLOAD = frozenset({"source_path", "rights"})
_SOFTWARE_RIGHTS = frozenset({"owned", "licensed", "observation_only"})
_SENSITIVE_PATH_MARKERS = frozenset({".ssh", ".aws", ".env", ".run", ".git", "credentials", "tokens", "private_material", "owner_voice", "audition-ledger"})
_MAX_OUTPUT = 2_000_000


def _authorized_context(*, authorization: Any, routing_decision: Any, capability_id: str):
    # The authority token must exist in persistent storage; never trust a payload copy.
    auth = validate_harness_authorization(
        authorization, expected_action="RESEARCH",
        expected_subject=f"capability:{capability_id}",
    )
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
    record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
    if record is None or not record.execution_enabled:
        raise PermissionError("REVERSE_ENGINEERING_CAPABILITY_NOT_ENABLED")
    if routing_decision.selected_capability_id != capability_id:
        raise PermissionError("REVERSE_ENGINEERING_ROUTING_MISMATCH")
    if routing_decision.authorized_action != "RESEARCH":
        raise PermissionError("REVERSE_ENGINEERING_ACTION_MISMATCH")
    if routing_decision.selected_executor_binding != record.executor_binding:
        raise PermissionError("REVERSE_ENGINEERING_EXECUTOR_BINDING_MISMATCH")
    return auth


def _scope(auth: Any, path: str, *, allow_dir: bool = False) -> Path:
    roots = auth.lineage.get("allowed_media_roots")
    if not isinstance(roots, list) or not roots or len(roots) > 8:
        raise PermissionError("REVERSE_ENGINEERING_ROOT_SCOPE_REQUIRED")
    raw = Path(str(path or "")).expanduser()
    if not raw.is_absolute():
        raise PermissionError("REVERSE_ENGINEERING_ABSOLUTE_PATH_REQUIRED")
    if raw.is_symlink():
        raise PermissionError("REVERSE_ENGINEERING_SYMLINK_FORBIDDEN")
    try:
        target = raw.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PermissionError("REVERSE_ENGINEERING_TARGET_UNAVAILABLE") from exc
    if target.is_dir() != bool(allow_dir) or not (target.is_dir() or target.is_file()):
        raise PermissionError("REVERSE_ENGINEERING_TARGET_TYPE_INVALID")
    if any(x.casefold() in _SENSITIVE_PATH_MARKERS for x in target.parts):
        raise PermissionError("REVERSE_ENGINEERING_PRIVATE_PATH_FORBIDDEN")
    permitted = False
    for item in roots:
        root = Path(str(item or "")).expanduser()
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            continue
        try:
            resolved_root = root.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if any(x.casefold() in _SENSITIVE_PATH_MARKERS for x in resolved_root.parts):
            continue
        if target != resolved_root and resolved_root in target.parents:
            permitted = True
            break
    if not permitted:
        raise PermissionError("REVERSE_ENGINEERING_PATH_OUTSIDE_HARNESS_SCOPE")
    return target


def _payload(payload: Any, permitted: frozenset[str]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not set(payload).issubset(permitted):
        raise PermissionError("REVERSE_ENGINEERING_UNKNOWN_OR_FORBIDDEN_PAYLOAD")
    if not isinstance(payload.get("source_path"), str):
        raise PermissionError("REVERSE_ENGINEERING_SOURCE_REQUIRED")
    if payload.get("rights") not in _SOFTWARE_RIGHTS:
        raise PermissionError("REVERSE_ENGINEERING_RIGHTS_DECLARATION_REQUIRED")
    return dict(payload)


def execute_authorized_media_observation(
    *, authorization: Any, routing_decision: Any, payload: dict[str, Any]
) -> dict[str, Any]:
    auth = _authorized_context(
        authorization=authorization, routing_decision=routing_decision,
        capability_id=MEDIA_CAPABILITY_ID,
    )
    args = _payload(payload, _ALLOWED_MEDIA_PAYLOAD)
    source = _scope(auth, args["source_path"])
    transcript_path = args.get("transcript_path")
    transcript = _scope(auth, transcript_path) if transcript_path is not None else None
    if type(args.get("include_scene_cuts", False)) is not bool:
        raise PermissionError("REVERSE_ENGINEERING_SCENE_FLAG_INVALID")
    observation = analyze_forensics(
        source, rights=args["rights"], transcript=transcript,
        include_scene_cuts=args.get("include_scene_cuts", False),
    )
    return {
        "schema_version": "BRHarnessReverseEngineeringResult/v1",
        "capability_id": MEDIA_CAPABILITY_ID,
        "authorization_id": auth.authorization_id,
        "harness_decision_id": auth.harness_decision_id,
        "execution_id": auth.execution_id,
        "status": "MEASURED",
        "evidence": observation,
        "approval": "NOT_REQUESTED",
        "production_mutation": False,
        "authority": "DEEPSEEK_HARNESS",
    }


def execute_authorized_software_observation(
    *, authorization: Any, routing_decision: Any, payload: dict[str, Any]
) -> dict[str, Any]:
    auth = _authorized_context(
        authorization=authorization, routing_decision=routing_decision,
        capability_id=REA_CAPABILITY_ID,
    )
    args = _payload(payload, _ALLOWED_SOFTWARE_PAYLOAD)
    source = _scope(auth, args["source_path"], allow_dir=True)
    # Static JS mode only: no native engines, debugger, browser or launched target.
    prefix = Path(os.environ.get("BR_REA_INSTALL_PREFIX", "")).expanduser()
    if not prefix.is_absolute() or prefix.is_symlink():
        raise ObservationError("REA_INSTALL_PREFIX_NOT_PROVEN")
    binary = prefix / "node_modules" / ".bin" / "rea"
    if not binary.is_file() or binary.is_symlink():
        raise ObservationError("REA_EXACT_BINARY_MISSING")
    try:
        version = subprocess.run(
            [str(binary), "--version"], capture_output=True, text=True,
            timeout=12, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ObservationError("REA_BINARY_UNAVAILABLE") from exc
    if version.returncode or version.stdout.strip() != "6.0.0":
        raise ObservationError("REA_VERSION_MISMATCH")
    try:
        result = subprocess.run(
            [str(binary), "analyze-javascript-application", str(source), "--json"],
            capture_output=True, text=True, timeout=120, check=False,
            cwd=str(source),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ObservationError("REA_STATIC_ANALYSIS_FAILED") from exc
    if result.returncode:
        raise ObservationError("REA_STATIC_ANALYSIS_FAILED")
    output = result.stdout
    if len(output) > _MAX_OUTPUT:
        raise ObservationError("REA_STATIC_RESULT_TOO_LARGE")
    try:
        envelope = json.loads(output)
    except ValueError as exc:
        raise ObservationError("REA_STATIC_EVIDENCE_INVALID") from exc
    if not isinstance(envelope, dict):
        raise ObservationError("REA_STATIC_EVIDENCE_INVALID")
    # No source text, decompilation or untrusted model instructions are surfaced
    # to the downstream agent. The full Evidence remains transient in memory.
    return {
        "schema_version": "BRHarnessReverseEngineeringResult/v1",
        "capability_id": REA_CAPABILITY_ID,
        "authorization_id": auth.authorization_id,
        "harness_decision_id": auth.harness_decision_id,
        "execution_id": auth.execution_id,
        "status": "MEASURED",
        "evidence": {
            "schema_version": "BRREAStaticObservation/v1",
            "rea_version": "6.0.0",
            "mode": "STATIC_JAVASCRIPT",
            "source_basename": source.name,
            "result_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
            "result_top_level_keys": sorted(str(key) for key in envelope)[:50],
            "limitations": "result digest only; no claim of runtime behavior or original source",
        },
        "approval": "NOT_REQUESTED",
        "production_mutation": False,
        "authority": "DEEPSEEK_HARNESS",
    }
