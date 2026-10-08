"""Read-only specialist executor behind the existing DeepSeek Harness authorization.

Never invoke this directly from external content. Task routing and persisted
authorization precede all analysis, not merely logging. No agent can grant scope.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any

from app.services.harness_authorization_service import validate_harness_authorization
from app.services.reverse_engineering_media_service import ObservationError, _source
from app.services.reverse_engineering_forensics_service import analyze_forensics
from app.services.reverse_engineering_learning_proposal_service import plan_original_experiment

MEDIA_CAPABILITY_ID = "reverse-engineering.media.observe"
REA_CAPABILITY_ID = "reverse-engineering.software.rea-static"
WEB_HAR_CAPABILITY_ID = "reverse-engineering.web.har-observe"
EXPERIMENT_CAPABILITY_ID = "reverse-engineering.experiment.assess"
FIDELITY_CAPABILITY_ID = "reverse-engineering.reconstruction.fidelity"
STUDIO_CAPABILITY_ID = "reverse-engineering.studio.forensics"
IRIS_CAPABILITY_ID = "reverse-engineering.web.iris-vision"
MEDIA_EXECUTOR_BINDING = "app.services.reverse_engineering_harness_service.execute_authorized_media_observation"
REA_EXECUTOR_BINDING = "app.services.reverse_engineering_harness_service.execute_authorized_software_observation"
WEB_HAR_EXECUTOR_BINDING = "app.services.reverse_engineering_harness_service.execute_authorized_web_har_observation"
_ALLOWED_MEDIA_PAYLOAD = frozenset({"source_path", "rights", "transcript_path", "include_scene_cuts", "include_audio_dynamics", "adaptive_shot_window_seconds", "adaptive_shot_start_seconds", "owner_goal", "candidate_path", "candidate_rights"})
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
    if type(args.get("include_audio_dynamics", False)) is not bool:
        raise PermissionError("REVERSE_ENGINEERING_DYNAMICS_FLAG_INVALID")
    if args.get("adaptive_shot_window_seconds") is not None:
        shot = args["adaptive_shot_window_seconds"]
        if type(shot) not in (float, int) or not 0 < shot <= 90:
            raise PermissionError("REVERSE_ENGINEERING_SHOT_WINDOW_INVALID")
    start = args.get("adaptive_shot_start_seconds", 0.0)
    if type(start) not in (float, int) or not math.isfinite(start) or start < 0 or (start > 0 and args.get("adaptive_shot_window_seconds") is None):
        raise PermissionError("REVERSE_ENGINEERING_SHOT_START_INVALID")
    observation = analyze_forensics(
        source, rights=args["rights"], transcript=transcript,
        include_scene_cuts=args.get("include_scene_cuts", False),
        include_audio_dynamics=args.get("include_audio_dynamics", False),
        adaptive_shot_window_seconds=args.get("adaptive_shot_window_seconds"),
        adaptive_shot_start_seconds=start,
    )
    candidate = None
    if args.get("candidate_path") is not None:
        if not isinstance(args["candidate_path"], str) or args.get("candidate_rights") not in {"owned", "licensed"}:
            raise PermissionError("REVERSE_ENGINEERING_ORIGINAL_CANDIDATE_REQUIRED")
        candidate_source = _scope(auth, args["candidate_path"])
        candidate = analyze_forensics(candidate_source, rights=args["candidate_rights"])
    if (args.get("owner_goal") is None) != (args.get("candidate_path") is None):
        # Goal-only study is permitted; a candidate requires an explicit owner goal.
        if args.get("candidate_path") is not None:
            raise PermissionError("REVERSE_ENGINEERING_OWNER_GOAL_REQUIRED")
    proposal = plan_original_experiment(
        reference=observation,
        owner_goal=args["owner_goal"],
        candidate=candidate,
    ) if args.get("owner_goal") is not None else None
    return {
        "schema_version": "BRHarnessReverseEngineeringResult/v1",
        "capability_id": MEDIA_CAPABILITY_ID,
        "authorization_id": auth.authorization_id,
        "harness_decision_id": auth.harness_decision_id,
        "execution_id": auth.execution_id,
        "status": "MEASURED",
        "evidence": observation,
        "learning_proposal": proposal,
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
    if not binary.is_file():
        raise ObservationError("REA_EXACT_BINARY_MISSING")
    if binary.is_symlink() and (prefix.resolve() / "node_modules") not in binary.resolve().parents:
        raise ObservationError("REA_BINARY_OUTSIDE_PINNED_PREFIX")
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


def execute_authorized_web_har_observation(
    *, authorization: Any, routing_decision: Any, payload: dict[str, Any],
) -> dict[str, Any]:
    """Inspect a stored HAR without any network or browser execution."""
    auth = _authorized_context(
        authorization=authorization, routing_decision=routing_decision,
        capability_id=WEB_HAR_CAPABILITY_ID,
    )
    args = _payload(payload, frozenset({"source_path", "rights"}))
    source = _scope(auth, args["source_path"])
    from app.services.reverse_engineering_web_har_service import analyze_web_har
    observation = analyze_web_har(source, rights=args["rights"])
    return {
        "schema_version": "BRHarnessReverseEngineeringResult/v1",
        "capability_id": WEB_HAR_CAPABILITY_ID,
        "authorization_id": auth.authorization_id,
        "harness_decision_id": auth.harness_decision_id,
        "execution_id": auth.execution_id,
        "status": "MEASURED",
        "evidence": observation,
        "approval": "NOT_REQUESTED",
        "production_mutation": False,
        "authority": "DEEPSEEK_HARNESS",
    }


def execute_authorized_experiment_assessment(
    *, authorization: Any, routing_decision: Any, payload: dict[str, Any],
) -> dict[str, Any]:
    """Gate statistical evaluation on persisted exact-dataset Harness authority.

    Does not read a source, run a media processor, schedule, learn, or change
    routing. Only hashes and scalar outcomes may cross this evaluation boundary.
    """
    auth = _authorized_context(
        authorization=authorization, routing_decision=routing_decision,
        capability_id=EXPERIMENT_CAPABILITY_ID,
    )
    if not isinstance(payload, dict) or set(payload) != {
        "dataset", "observations", "allowed_technique_ids",
    }:
        raise PermissionError("EXPERIMENT_PAYLOAD_SCHEMA_FORBIDDEN")
    allowed = auth.lineage.get("allowed_technique_ids")
    if (not isinstance(allowed, list) or len(allowed) > 8 or
        not allowed or payload["allowed_technique_ids"] != allowed):
        raise PermissionError("EXPERIMENT_TECHNIQUE_AUTHORIZATION_MISMATCH")
    pinned_hash = auth.lineage.get("experiment_dataset_sha256")
    dataset = payload["dataset"]
    if (not isinstance(dataset, dict) or not isinstance(pinned_hash, str) or
        dataset.get("dataset_sha256") != pinned_hash):
        raise PermissionError("EXPERIMENT_DATASET_AUTHORIZATION_MISMATCH")
    if (auth.lineage.get("experiment_domain") != dataset.get("domain") or
        auth.lineage.get("experiment_task_class") != dataset.get("task_class")):
        raise PermissionError("EXPERIMENT_DOMAIN_AUTHORIZATION_MISMATCH")
    from app.services.reverse_engineering_experiment_intelligence_v4 import (
        assess_technique_experiments, choose_next_benchmark,
    )
    report = assess_technique_experiments(
        dataset=dataset,
        observations=payload["observations"],
        allowed_technique_ids=allowed,
    )
    followup = choose_next_benchmark(
        assessment=report, eligible_technique_ids=allowed,
    )
    return {
        "schema_version": "BRHarnessReverseEngineeringResult/v1",
        "capability_id": EXPERIMENT_CAPABILITY_ID,
        "authorization_id": auth.authorization_id,
        "harness_decision_id": auth.harness_decision_id,
        "execution_id": auth.execution_id,
        "status": "ASSESSED_NOT_LEARNED",
        "evidence": report,
        "next_benchmark_proposal": followup,
        "approval": "NOT_REQUESTED",
        "memory_write": "NOT_ATTEMPTED",
        "production_mutation": False,
        "authority": "DEEPSEEK_HARNESS",
    }


def execute_authorized_fidelity_assessment(
    *, authorization: Any, routing_decision: Any, payload: dict[str, Any],
) -> dict[str, Any]:
    """Compare a licensed reconstruction against its matching authorized source.

    Trusted Harness authorization and exact local allowed roots must precede
    every media decode. This never writes results into canonical learning.
    """
    auth = _authorized_context(
        authorization=authorization, routing_decision=routing_decision,
        capability_id=FIDELITY_CAPABILITY_ID,
    )
    if not isinstance(payload, dict) or set(payload) != {
        "reference_path", "candidate_path", "reference_rights", "candidate_rights",
        "window_seconds",
    }:
        raise PermissionError("FIDELITY_PAYLOAD_SCHEMA_INVALID")
    if payload["reference_rights"] not in {"owned", "licensed"} or payload["candidate_rights"] not in {"owned", "licensed"}:
        raise PermissionError("FIDELITY_EXPRESSION_RIGHTS_UNVERIFIED")
    ref = _scope(auth, payload["reference_path"])
    can = _scope(auth, payload["candidate_path"])
    if ref == can:
        raise PermissionError("FIDELITY_RECONSTRUCTION_MUST_BE_DISTINCT")
    from app.services.reverse_engineering_fidelity_v5_service import compare_reconstruction
    report = compare_reconstruction(
        ref, can,
        rights=payload["reference_rights"],
        candidate_rights=payload["candidate_rights"],
        window_seconds=payload["window_seconds"],
    )
    return {
        "schema_version": "BRHarnessReverseEngineeringResult/v1",
        "capability_id": FIDELITY_CAPABILITY_ID,
        "authorization_id": auth.authorization_id,
        "harness_decision_id": auth.harness_decision_id,
        "execution_id": auth.execution_id,
        "status": "TECHNICAL_MEASUREMENTS_ONLY",
        "evidence": report,
        "approval": "NOT_REQUESTED",
        "production_mutation": False,
        "memory_write": "NOT_ATTEMPTED",
        "authority": "DEEPSEEK_HARNESS",
    }


def execute_authorized_studio_observation(
    *, authorization: Any, routing_decision: Any, payload: dict[str, Any],
) -> dict[str, Any]:
    """A single scoped entrypoint for four independently testable studio probes.

    Domain workers never access the owner voice sample directory or generate
    synthetic/cloned media. Only user-owned or licensed local inputs are accepted.
    """
    auth = _authorized_context(
        authorization=authorization, routing_decision=routing_decision,
        capability_id=STUDIO_CAPABILITY_ID,
    )
    if not isinstance(payload,dict) or set(payload) != {"mode","rights","inputs","options"}:
        raise PermissionError("STUDIO_HARNESS_PAYLOAD_SCHEMA_INVALID")
    if payload["rights"] not in ("owned","licensed") or not isinstance(payload["options"],dict):
        raise PermissionError("STUDIO_HARNESS_RIGHTS_OR_OPTIONS_INVALID")
    mode=payload["mode"]
    allowed={
        "stems":({"window_seconds"},2,4),
        "motion":({"max_frames"},1,1),
        "alignment":(set(),2,2),
        "timeline":(set(),1,1),
    }
    if mode not in allowed:
        raise PermissionError("STUDIO_HARNESS_MODE_INVALID")
    accepted,min_inputs,max_inputs=allowed[mode]
    inp=payload["inputs"]
    if not isinstance(inp,list) or not min_inputs<=len(inp)<=max_inputs or not set(payload["options"]).issubset(accepted):
        raise PermissionError("STUDIO_HARNESS_INPUTS_OR_OPTIONS_INVALID")
    if not all(isinstance(p,str) and p for p in inp):
        raise PermissionError("STUDIO_HARNESS_INPUT_PATH_INVALID")
    if mode in ("stems","motion") and payload["rights"]=="licensed":
        # All licensed materials must be explicitly authorized in the persisted roots;
        # documentary license checks still occur outside this service.
        pass
    sources=[_scope(auth,p) for p in inp]
    from app.services import reverse_engineering_studio_v6_service as studio
    if mode=="stems":
        output=studio.analyze_stems(sources,**payload["options"])
    elif mode=="motion":
        output=studio.analyze_animation_motion(sources[0],**payload["options"])
    elif mode=="alignment":
        output=studio.audit_external_word_alignment(sources[0],sources[1])
    else:
        output=studio.compile_original_timeline(sources[0])
    return {
        "schema_version":"BRHarnessReverseEngineeringResult/v1",
        "capability_id":STUDIO_CAPABILITY_ID,
        "authorization_id":auth.authorization_id,
        "harness_decision_id":auth.harness_decision_id,
        "execution_id":auth.execution_id,
        "status":"EVIDENCE_ONLY",
        "mode":mode,
        "evidence":output,
        "approval":"NOT_REQUESTED",
        "publication":"FORBIDDEN",
        "production_mutation":False,
        "memory_write":"NOT_ATTEMPTED",
        "authority":"DEEPSEEK_HARNESS",
    }


def execute_authorized_iris_capture(
    *, authorization: Any, routing_decision: Any, payload: dict[str, Any],
) -> dict[str, Any]:
    """A single owned-file visual observation, not a generic browser MCP bridge."""
    auth = _authorized_context(
        authorization=authorization, routing_decision=routing_decision,
        capability_id=IRIS_CAPABILITY_ID,
    )
    if not isinstance(payload, dict) or set(payload) != {
        "source_path", "output_path", "rights", "viewport", "selector"
    }:
        raise PermissionError("IRIS_HARNESS_PAYLOAD_SCHEMA_INVALID")
    if payload["rights"] != "owned":
        raise PermissionError("IRIS_HARNESS_ONLY_OWNED_STATIC_PAGES")
    src = _scope(auth, payload["source_path"])
    out = Path(str(payload["output_path"]))
    raw_roots = auth.lineage.get("allowed_vision_output_roots")
    if not isinstance(raw_roots, list) or not 1 <= len(raw_roots) <= 4:
        raise PermissionError("IRIS_HARNESS_PRIVATE_OUTPUT_ROOT_REQUIRED")
    if not out.is_absolute() or out.suffix != ".png" or out.exists() or out.is_symlink():
        raise PermissionError("IRIS_HARNESS_OUTPUT_SCOPE_INVALID")
    try:
        parent = out.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PermissionError("IRIS_HARNESS_OUTPUT_PARENT_INVALID") from exc
    if not parent.is_dir() or parent != out.parent:
        raise PermissionError("IRIS_HARNESS_OUTPUT_PARENT_SYMLINKED")
    permitted = False
    for value in raw_roots:
        base = Path(str(value or ""))
        if not base.is_absolute() or base.is_symlink() or not base.is_dir():
            continue
        try:
            root = base.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if (root == parent or root in parent.parents) and not any(
            part.casefold() in _SENSITIVE_PATH_MARKERS for part in parent.parts
        ):
            permitted = True
            break
    if not permitted:
        raise PermissionError("IRIS_HARNESS_OUTPUT_OUTSIDE_PRIVATE_SCOPE")
    binary_path = os.getenv("BR_IRIS_PINNED_BIN")
    if not binary_path:
        raise PermissionError("IRIS_HARNESS_PINNED_BINARY_REQUIRED")
    from app.services.reverse_engineering_iris_v7_service import capture_owned_static_page
    evidence = capture_owned_static_page(
        source_path=src, output_path=out, iris_binary=binary_path,
        size=payload["viewport"], selector=payload["selector"],
    )
    return {
        "schema_version": "BRHarnessReverseEngineeringResult/v1",
        "capability_id": IRIS_CAPABILITY_ID,
        "authorization_id": auth.authorization_id,
        "harness_decision_id": auth.harness_decision_id,
        "execution_id": auth.execution_id,
        "status": "PRIVATE_VISUAL_CAPTURED",
        "evidence": evidence, "approval": "NOT_REQUESTED",
        "owner_voice_access": "FORBIDDEN", "network_site_capture": "NOT_ATTEMPTED",
        "memory_write": "NOT_ATTEMPTED", "production_mutation": False,
        "publication": "FORBIDDEN", "authority": "DEEPSEEK_HARNESS",
    }
