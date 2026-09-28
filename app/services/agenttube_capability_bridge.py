from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from statistics import mean
from typing import Any, Iterable

from app.contracts.harness_specialized_worker_contracts import TaskExecutionEnvelope
from app.services.capability_execution_contract_service import (
    CAN_CONSUME_ARTIFACT_REFS,
    CAN_PRODUCE_ARTIFACT_REFS,
)
from app.services.global_capability_registry_base import (
    AVAILABLE,
    FUNCTIONAL,
    CapabilityRecord,
)
from app.services.typed_task_requirement_service import (
    TYPED_TASK_REQUIREMENT_SCHEMA,
    TypedTaskRequirement,
)


AGENTTUBE_REPOSITORY = "darkzOGx/youtube-automation-agent"
AGENTTUBE_SHA = "0d7eaf9628ce84e34103f1d1c263dfd89027547e"
AGENTTUBE_TREE_SHA = "3e7d2533c70b829c8ae1441adb79251867fe94d7"
AGENTTUBE_PACKAGE_VERSION = "2.10.0"
AGENTTUBE_PACKAGE_LOCK_DIGEST = (
    "sha256:64cba342c01d4bc1a6d7aeb4fcb095ac6280470e50818a207219baec0b4cce2d"
)
EXECUTOR_BINDING = (
    "app.services.agenttube_capability_bridge.execute_agenttube_capability"
)
RESULT_SCHEMA = "AgentTubeCapabilityResult/v1"
INPUT_SCHEMA = "AgentTubeCapabilityInput/v1"

OFFICIAL_OPENING = (
    "Booooa meu povo, aqui é BR no GTA 6 e hoje vamos de [tema do vídeo]!"
)
OFFICIAL_CLOSING = "E BR não dorme em Vice City"


@dataclass(frozen=True)
class AgentTubeCapabilitySpec:
    capability_id: str
    source_project: str
    source_sha: str
    source_file: str
    functional_role: str
    execution_kind: str
    domain: str
    side_effect_class: str
    required_tools: tuple[str, ...]
    input_schema: str
    output_schema: str
    hard_eligibility: tuple[str, ...]
    human_gate_policy: str
    learning_eligibility: str
    version: str
    allowed_actions: tuple[str, ...]
    authority: str = "NONE"
    routing_authority: str = "NONE"
    learning_promotion_authority: str = "NONE"


def agenttube_capability_specs() -> tuple[AgentTubeCapabilitySpec, ...]:
    common = (
        "TaskExecutionEnvelope/v1",
        "TypedTaskRequirement/v1",
        "DeepSeek Harness authorization",
        "exact pinned AgentTube source SHA",
        "fallback_eligibility=false",
        "zero-cost adapter execution",
    )
    return (
        AgentTubeCapabilitySpec(
            capability_id="youtube.content-strategy",
            source_project="AgentTube/Lumen",
            source_sha=AGENTTUBE_SHA,
            source_file="agents/content-strategy-agent.js",
            functional_role="EDITORIAL_STRATEGY",
            execution_kind="DETERMINISTIC_WORKER",
            domain="youtube-editorial",
            side_effect_class="READ_ONLY",
            required_tools=(),
            input_schema=INPUT_SCHEMA,
            output_schema=RESULT_SCHEMA,
            hard_eligibility=common + (
                "verified evidence refs required for factual GTA6 claims",
                "GTA6 Brain remains domain evidence authority",
            ),
            human_gate_policy="NONE",
            learning_eligibility="LEARNING_CANDIDATE_ONLY",
            version="1",
            allowed_actions=("RESEARCH", "EDITORIAL", "EXECUTION"),
        ),
        AgentTubeCapabilitySpec(
            capability_id="youtube.script-writing",
            source_project="AgentTube/Lumen",
            source_sha=AGENTTUBE_SHA,
            source_file="agents/script-writer-agent.js",
            functional_role="EDITORIAL_GENERATION",
            execution_kind="DETERMINISTIC_WORKER",
            domain="youtube-editorial",
            side_effect_class="READ_ONLY",
            required_tools=(),
            input_schema=INPUT_SCHEMA,
            output_schema=RESULT_SCHEMA,
            hard_eligibility=common + (
                "evidence map required",
                "PT-BR canonical narration",
                "20-25 minute final-video contract",
                "novelty/repetition gates preserved",
            ),
            human_gate_policy="NONE",
            learning_eligibility="LEARNING_CANDIDATE_ONLY",
            version="1",
            allowed_actions=("EDITORIAL",),
        ),
        AgentTubeCapabilitySpec(
            capability_id="youtube.thumbnail-design",
            source_project="AgentTube/Lumen",
            source_sha=AGENTTUBE_SHA,
            source_file="agents/thumbnail-designer-agent.js",
            functional_role="THUMBNAIL_DESIGN",
            execution_kind="DETERMINISTIC_WORKER",
            domain="youtube-packaging",
            side_effect_class="READ_ONLY",
            required_tools=(),
            input_schema=INPUT_SCHEMA,
            output_schema=RESULT_SCHEMA,
            hard_eligibility=common + (
                "BR-no-GTA branding remains authority",
                "no logo/watermark mutation",
            ),
            human_gate_policy="HUMAN_REVIEW_BEFORE_APPLY",
            learning_eligibility="LEARNING_CANDIDATE_ONLY",
            version="1",
            allowed_actions=("EDITORIAL", "EXECUTION"),
        ),
        AgentTubeCapabilitySpec(
            capability_id="youtube.discoverability",
            source_project="AgentTube/Lumen",
            source_sha=AGENTTUBE_SHA,
            source_file="agents/seo-optimizer-agent.js",
            functional_role="DISCOVERABILITY",
            execution_kind="DETERMINISTIC_WORKER",
            domain="youtube-metadata",
            side_effect_class="READ_ONLY",
            required_tools=(),
            input_schema=INPUT_SCHEMA,
            output_schema=RESULT_SCHEMA,
            hard_eligibility=common + (
                "metadata output is advisory",
                "no publication authority",
            ),
            human_gate_policy="BUNDLED_APPLY_ONLY_WITHIN_HARNESS_POLICY",
            learning_eligibility="LEARNING_CANDIDATE_ONLY",
            version="1",
            allowed_actions=("EDITORIAL", "EXECUTION"),
        ),
        AgentTubeCapabilitySpec(
            capability_id="youtube.production",
            source_project="AgentTube/Lumen",
            source_sha=AGENTTUBE_SHA,
            source_file="agents/production-management-agent.js",
            functional_role="PRODUCTION",
            execution_kind="DETERMINISTIC_WORKER",
            domain="production",
            side_effect_class="READ_ONLY",
            required_tools=(),
            input_schema=INPUT_SCHEMA,
            output_schema=RESULT_SCHEMA,
            hard_eligibility=common + (
                "existing BR render pipeline remains authority",
                "scene changes use causal localized invalidation",
                "no paid provider probe without human confirmation",
            ),
            human_gate_policy="EXISTING_BR_PRODUCTION_GATES",
            learning_eligibility="LEARNING_CANDIDATE_ONLY",
            version="1",
            allowed_actions=("EXECUTION",),
        ),
        AgentTubeCapabilitySpec(
            capability_id="youtube.publishing",
            source_project="AgentTube/Lumen",
            source_sha=AGENTTUBE_SHA,
            source_file="agents/publishing-scheduling-agent.js",
            functional_role="PUBLISHING",
            execution_kind="DETERMINISTIC_WORKER",
            domain="youtube-publication",
            side_effect_class="EXTERNAL_MUTATION",
            required_tools=(),
            input_schema=INPUT_SCHEMA,
            output_schema=RESULT_SCHEMA,
            hard_eligibility=common + (
                "publication_id required",
                "Harness PUBLICATION authorization required",
                "br_youtube_pode_postar(publication_id) required",
                "no fallback publication route",
            ),
            human_gate_policy="br_youtube_pode_postar(publication_id)",
            learning_eligibility="NOT_ELIGIBLE",
            version="1",
            allowed_actions=("PUBLICATION",),
        ),
        AgentTubeCapabilitySpec(
            capability_id="youtube.analytics-learning",
            source_project="AgentTube/Lumen",
            source_sha=AGENTTUBE_SHA,
            source_file="agents/analytics-optimization-agent.js",
            functional_role="ANALYSIS",
            execution_kind="DETERMINISTIC_ANALYSIS_AGENT",
            domain="youtube-analytics",
            side_effect_class="READ_ONLY",
            required_tools=(),
            input_schema=INPUT_SCHEMA,
            output_schema=RESULT_SCHEMA,
            hard_eligibility=common + (
                "real analytics distinguished from simulated/unknown/missing",
                "Learning Plane is sole promotion authority",
            ),
            human_gate_policy="NONE",
            learning_eligibility="PROPOSE_ONLY",
            version="1",
            allowed_actions=("EXECUTION",),
        ),
    )


def _security_boundary(spec: AgentTubeCapabilitySpec) -> str:
    return (
        "DeepSeek Harness is sole authority. AgentTube is a pinned subordinate "
        "capability source only; Lumen, upstream scheduler, SQLite state, credential "
        "manager, publishing logic and learning logic are not control planes. "
        "The local adapter consumes canonical typed task contracts, performs no "
        "implicit network/provider/publication action, cannot write canonical memory, "
        "cannot expand routing, and cannot bypass BR-no-GTA human/publication gates. "
        f"Source={AGENTTUBE_REPOSITORY}@{AGENTTUBE_SHA}; gate={spec.human_gate_policy}."
    )


def agenttube_capability_records() -> tuple[CapabilityRecord, ...]:
    records: list[CapabilityRecord] = []
    for spec in agenttube_capability_specs():
        records.append(
            CapabilityRecord(
                capability_id=spec.capability_id,
                capability_type="CAPABILITY",
                domain=spec.domain,
                implementation=(
                    "BR-no-GTA contract/algorithm adaptation of pinned AgentTube "
                    f"{spec.source_file}; upstream runtime is not executed"
                ),
                input_contract=(
                    "TaskExecutionEnvelope/v1 + TypedTaskRequirement/v1 + "
                    "AgentTubeCapabilityInput/v1"
                ),
                output_contract=RESULT_SCHEMA,
                requirements=spec.hard_eligibility,
                maturity=FUNCTIONAL,
                availability=AVAILABLE,
                allowed_actions=spec.allowed_actions,
                policy_tags=(
                    "agenttube",
                    "youtube",
                    "subordinate",
                    "pinned-upstream",
                    spec.functional_role.lower().replace("_", "-"),
                ),
                security_boundary=_security_boundary(spec),
                cost_class="FREE_NO_BILLING",
                quota_class="LOCAL_DETERMINISTIC",
                latency_class="LOCAL",
                quality_class="TYPED_FAIL_CLOSED_HARNESS_GOVERNED",
                evidence_contract=RESULT_SCHEMA,
                fallback_eligibility=False,
                executor_binding=EXECUTOR_BINDING,
                version=spec.version,
                provider_id="agenttube-pinned",
                agent_id=spec.source_file.rsplit("/", 1)[-1].removesuffix(".js"),
                side_effects=(),
                authority="NONE",
                memory_write="FORBIDDEN",
                routing_authority="NONE",
                editorial_authority="NONE",
                publication_authority="NONE",
                supports_parallelism=True,
                supports_retry=False,
                supports_resume=True,
                supports_review=True,
                side_effect_class=spec.side_effect_class,
                default_read_scope=("artifacts", "content", "brain/analytics"),
                default_write_scope=(),
                allowed_tools=(),
                health_policy="PINNED_SOURCE_CONTRACT_ONLY",
                execution_operations=(
                    CAN_CONSUME_ARTIFACT_REFS,
                    CAN_PRODUCE_ARTIFACT_REFS,
                ),
                execution_kind=spec.execution_kind,
                functional_roles=(spec.functional_role,),
                output_contract_ids=(RESULT_SCHEMA,),
            )
        )
    return tuple(records)


def _validate_canonical_task(
    capability_id: str,
    payload: dict[str, Any],
) -> tuple[TaskExecutionEnvelope, TypedTaskRequirement, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("AgentTube payload must be an object")
    raw_envelope = payload.get("task_envelope")
    if not isinstance(raw_envelope, dict):
        raise ValueError("TaskExecutionEnvelope/v1 is required")
    envelope = TaskExecutionEnvelope(**raw_envelope)
    if envelope.schema != "TaskExecutionEnvelope/v1":
        raise ValueError("unsupported task execution envelope schema")
    if envelope.required_capability != capability_id:
        raise PermissionError("AgentTube capability does not match TaskExecutionEnvelope")
    if envelope.expected_output_schema != RESULT_SCHEMA:
        raise ValueError("AgentTube TaskExecutionEnvelope output schema mismatch")

    raw_requirement = payload.get("typed_requirement")
    if not isinstance(raw_requirement, dict):
        raise ValueError("TypedTaskRequirement/v1 is required")
    requirement = TypedTaskRequirement.from_mapping(raw_requirement)
    if requirement.schema != TYPED_TASK_REQUIREMENT_SCHEMA:
        raise ValueError("unsupported typed task requirement schema")
    if requirement.task_id != envelope.task_id:
        raise PermissionError("typed task requirement task mismatch")
    if capability_id not in requirement.proposal_candidate_hints:
        raise PermissionError("typed task requirement does not name AgentTube capability")

    input_payload = payload.get("input") or {}
    if not isinstance(input_payload, dict):
        raise ValueError("AgentTube capability input must be an object")
    return envelope, requirement, input_payload


def _content_strategy(input_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "AgentTubeContentStrategyEvidence/v1",
        "evidence_refs": list(dict.fromkeys(input_payload.get("evidence_refs") or ())),
        "channel_history_refs": list(
            dict.fromkeys(input_payload.get("channel_history_refs") or ())
        ),
        "candidate_topics": list(input_payload.get("candidate_topics") or ()),
        "gta6_evidence_authority": "GTA6_BRAIN",
        "editorial_authority": "DEEPSEEK_HARNESS",
        "fact_invention_allowed": False,
    }


def _script_writing(input_payload: dict[str, Any]) -> dict[str, Any]:
    evidence_map_ref = str(input_payload.get("evidence_map_ref") or "").strip()
    if not evidence_map_ref:
        raise ValueError("script writing requires evidence_map_ref")
    target = float(input_payload.get("target_duration_minutes") or 22.0)
    if target < 20.0 or target > 25.0:
        raise ValueError("script target duration must stay within 20-25 minutes")
    language = str(input_payload.get("language") or "pt-BR")
    if language != "pt-BR":
        raise ValueError("BR-no-GTA canonical narration language must be pt-BR")
    return {
        "schema": "AgentTubeScriptWritingEvidence/v1",
        "evidence_map_ref": evidence_map_ref,
        "target_duration_minutes": target,
        "script_policy": {
            "opening": OFFICIAL_OPENING,
            "closing": OFFICIAL_CLOSING,
            "duration_min_minutes": 20,
            "duration_max_minutes": 25,
            "artificial_padding": False,
            "evidence_map_required": True,
            "novelty_gate_required": True,
            "repetition_gate_required": True,
            "canonical_language": "pt-BR",
        },
    }


def _thumbnail_design(input_payload: dict[str, Any]) -> dict[str, Any]:
    concepts = list(input_payload.get("concepts") or ())[:3]
    return {
        "schema": "AgentTubeThumbnailDesignEvidence/v1",
        "concepts": concepts,
        "max_variants": 3,
        "branding_authority": "BR-no-GTA",
        "logo_mutation_allowed": False,
        "watermark_mutation_allowed": False,
        "apply_requires_review": True,
    }


def _discoverability(input_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "AgentTubeDiscoverabilityEvidence/v1",
        "title_candidates": list(input_payload.get("title_candidates") or ())[:5],
        "description_candidate": input_payload.get("description_candidate"),
        "tags": list(dict.fromkeys(input_payload.get("tags") or ())),
        "hashtags": list(dict.fromkeys(input_payload.get("hashtags") or ())),
        "chapters": list(input_payload.get("chapters") or ()),
        "advisory_only": True,
        "publication_authority": "NONE",
    }


def build_scene_manifest(scenes: Iterable[dict[str, Any]]) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in scenes:
        if not isinstance(raw, dict):
            raise ValueError("scene must be an object")
        scene_id = str(raw.get("scene_id") or "").strip()
        if not scene_id or scene_id in seen:
            raise ValueError("scene_id must be unique and non-empty")
        seen.add(scene_id)
        duration = float(raw.get("duration") or 0)
        if duration <= 0:
            raise ValueError("scene duration must be positive")
        normalized.append(
            {
                "scene_id": scene_id,
                "position": int(raw.get("position") or len(normalized) + 1),
                "semantic_role": str(raw.get("semantic_role") or "content"),
                "script_text": str(raw.get("script_text") or ""),
                "visual_prompt": str(raw.get("visual_prompt") or ""),
                "duration": duration,
                "asset_id": raw.get("asset_id"),
                "asset_origin": raw.get("asset_origin"),
                "provider": raw.get("provider"),
                "model": raw.get("model"),
                "external_task_id": raw.get("external_task_id"),
                "rights_state": str(raw.get("rights_state") or "UNKNOWN"),
                "provenance_refs": list(raw.get("provenance_refs") or ()),
                "narration_asset_id": raw.get("narration_asset_id"),
                "narration_status": str(raw.get("narration_status") or "UNKNOWN"),
                "narration_provider": raw.get("narration_provider"),
                "narration_model": raw.get("narration_model"),
                "revision": int(raw.get("revision") or 1),
                "locked": bool(raw.get("locked", False)),
                "cost_evidence": raw.get("cost_evidence"),
                "qa_state": str(raw.get("qa_state") or "PENDING"),
            }
        )
    normalized.sort(key=lambda item: (item["position"], item["scene_id"]))
    return {
        "schema": "BRSceneManifest/v1",
        "scenes": normalized,
        "final_master_status": "PENDING",
        "local_qa_status": "PENDING",
    }


def revise_scene(
    manifest: dict[str, Any],
    *,
    scene_id: str,
    changes: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    if manifest.get("schema") != "BRSceneManifest/v1":
        raise ValueError("BRSceneManifest/v1 required")
    revised = deepcopy(manifest)
    target = None
    for scene in revised.get("scenes") or ():
        if scene.get("scene_id") == scene_id:
            target = scene
            break
    if target is None:
        raise ValueError("scene not found")
    if target.get("locked"):
        raise PermissionError("locked scene cannot be revised")
    forbidden = {"scene_id", "position", "revision"}
    if forbidden.intersection(changes):
        raise ValueError("scene identity/order/revision cannot be overwritten")
    old_script = str(target.get("script_text") or "")
    for key, value in changes.items():
        target[key] = value
    if str(target.get("script_text") or "") != old_script and "narration_status" not in changes:
        target["narration_status"] = "STALE"
    target["revision"] = int(target.get("revision") or 1) + 1
    target["qa_state"] = "STALE"
    revised["final_master_status"] = "STALE"
    revised["local_qa_status"] = "STALE"
    return {
        "schema": "BRSceneRevision/v1",
        "scene_id": scene_id,
        "reason": str(reason),
        "localized_scene_repair": True,
        "full_rebuild_required": False,
        "invalidated_scene_ids": [scene_id],
        "invalidated_outputs": ["final_master", "local_qa"],
        "manifest": revised,
    }


def _retention_class(values: list[float]) -> str:
    if not values:
        return "insufficient"
    if len(values) >= 2 and values[-1] <= values[0] - 0.15:
        return "drop_off"
    if max(values) >= values[0] + 0.05:
        return "rewatch"
    if mean(values) >= 0.70:
        return "strong_hold"
    return "steady"


def map_retention_to_scenes(
    manifest: dict[str, Any],
    curve: Iterable[dict[str, Any]],
    *,
    source_state: str,
) -> dict[str, Any]:
    if manifest.get("schema") != "BRSceneManifest/v1":
        raise ValueError("BRSceneManifest/v1 required")
    state = str(source_state or "").strip().upper()
    points: list[tuple[float, float]] = []
    for row in curve:
        if not isinstance(row, dict):
            continue
        time_value = row.get("time_seconds")
        retention_value = row.get("retention")
        if time_value is None or retention_value is None:
            continue
        points.append((float(time_value), float(retention_value)))
    points.sort()

    observations: list[dict[str, Any]] = []
    cursor = 0.0
    scenes = list(manifest.get("scenes") or ())
    for index, scene in enumerate(scenes):
        duration = float(scene.get("duration") or 0)
        end = cursor + duration
        values = [
            value
            for time_value, value in points
            if time_value >= cursor
            and (time_value < end or (index == len(scenes) - 1 and time_value <= end))
        ]
        if values:
            observations.append(
                {
                    "scene_id": scene.get("scene_id"),
                    "start_seconds": cursor,
                    "end_seconds": end,
                    "classification": _retention_class(values),
                    "mean_retention": mean(values),
                    "sample_count": len(values),
                }
            )
        cursor = end

    eligible = state == "REAL" and bool(observations)
    return {
        "schema": "SceneRetentionEvidence/v1",
        "source_state": state,
        "observations": observations,
        "eligible_for_learning": eligible,
        "missing_is_zero": False,
        "learning_candidate": {
            "schema": "LearningCandidate/v1",
            "candidate_type": "SCENE_RETENTION",
            "eligible_for_learning": eligible,
            "promotion_authority": "LEARNING_PLANE",
            "auto_promote": False,
        },
    }


def build_production_readiness_evidence(
    *,
    local_checks: dict[str, Any],
    paid_probes: Iterable[str] = (),
) -> dict[str, Any]:
    probes = [str(item) for item in paid_probes if str(item).strip()]
    duration = local_checks.get("duration_minutes")
    duration_ok = (
        True if duration is None else float(duration) >= 20.0
    )
    return {
        "schema": "ProductionReadinessEvidence/v1",
        "checks": dict(local_checks),
        "duration_gate_passed": duration_ok,
        "overlay_policy": "OFF",
        "caption_policy": "NO_BURN_IN",
        "local_zero_cost_checks_automatic": True,
        "paid_probes": probes,
        "paid_probe_status": (
            "HUMAN_CONFIRMATION_REQUIRED" if probes else "NOT_REQUESTED"
        ),
        "paid_side_effects": 0,
        "authority": "EXISTING_BR_PRODUCTION_GATES",
    }


def reconcile_upload_outcome(
    *,
    upload_state: str,
    publication_id: int,
    observed_youtube_video_id: str | None,
) -> dict[str, Any]:
    if isinstance(publication_id, bool) or int(publication_id) <= 0:
        raise ValueError("publication_id must be positive")
    state = str(upload_state or "").strip().upper()
    video_id = str(observed_youtube_video_id or "").strip() or None
    if state == "UPLOAD_OUTCOME_UNKNOWN":
        resolved = "RECONCILED" if video_id else "RECONCILIATION_REQUIRED"
    elif state == "UPLOAD_CONFIRMED":
        resolved = "UPLOAD_CONFIRMED"
    elif state in {
        "UPLOAD_NOT_ATTEMPTED",
        "UPLOAD_IN_PROGRESS",
        "RECONCILIATION_REQUIRED",
        "RECONCILED",
        "FAILED_CONFIRMED",
    }:
        resolved = state
    else:
        raise ValueError("unsupported upload state")
    return {
        "schema": "UploadOutcomeReconciliation/v1",
        "publication_id": int(publication_id),
        "state": resolved,
        "youtube_video_id": video_id,
        "retry_upload": False,
        "duplicate_upload_from_blind_retry": 0,
        "reconciliation_required": resolved == "RECONCILIATION_REQUIRED",
    }


def build_packaging_experiment_plan(
    *,
    experiment_id: str,
    arms: Iterable[str],
    minimum_impressions: int,
) -> dict[str, Any]:
    normalized = [str(item).strip() for item in arms if str(item).strip()]
    if "control" not in normalized:
        raise ValueError("packaging experiment requires control arm")
    if len(normalized) < 2 or len(normalized) > 3 or len(set(normalized)) != len(normalized):
        raise ValueError("packaging experiment must have 2-3 unique bounded arms")
    if int(minimum_impressions) <= 0:
        raise ValueError("minimum_impressions must be positive")
    return {
        "schema": "PackagingExperimentPlan/v1",
        "experiment_id": str(experiment_id),
        "arms": normalized,
        "minimum_impressions": int(minimum_impressions),
        "retention_guardrail_delta": 0.02,
        "traffic_source_shift_guardrail": 0.25,
        "bounded": True,
        "auto_apply_winner": False,
    }


def evaluate_packaging_experiment(
    plan: dict[str, Any],
    *,
    samples: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    if plan.get("schema") != "PackagingExperimentPlan/v1":
        raise ValueError("PackagingExperimentPlan/v1 required")
    rows: list[dict[str, Any]] = []
    for raw in samples:
        impressions = int(raw.get("impressions") or 0)
        clicks = int(raw.get("clicks") or 0)
        retention = float(raw.get("retention") or 0.0)
        rows.append(
            {
                "schema": "PackagingExperimentSample/v1",
                "arm": str(raw.get("arm") or ""),
                "impressions": impressions,
                "clicks": clicks,
                "ctr": (clicks / impressions) if impressions > 0 else None,
                "retention": retention,
                "traffic_source_shift": float(raw.get("traffic_source_shift") or 0.0),
            }
        )
    by_arm = {row["arm"]: row for row in rows}
    control = by_arm.get("control")
    winner = None
    if control and control["ctr"] is not None:
        eligible = [
            row
            for row in rows
            if row["impressions"] >= int(plan["minimum_impressions"])
            and row["ctr"] is not None
            and row["retention"]
            >= float(control["retention"]) - float(plan["retention_guardrail_delta"])
            and abs(float(row["traffic_source_shift"]))
            <= float(plan["traffic_source_shift_guardrail"])
        ]
        if eligible:
            candidate = max(eligible, key=lambda row: (float(row["ctr"]), row["arm"]))
            if candidate["arm"] != "control" and float(candidate["ctr"]) > float(control["ctr"]):
                winner = candidate["arm"]
    return {
        "schema": "PackagingExperimentEvidence/v1",
        "experiment_id": plan["experiment_id"],
        "samples": rows,
        "winner_candidate": winner,
        "restore_control": True,
        "auto_promoted": False,
        "learning_candidate": {
            "schema": "LearningCandidate/v1",
            "candidate_type": "PACKAGING_EXPERIMENT",
            "proposed_arm": winner,
            "promotion_authority": "LEARNING_PLANE",
            "auto_promote": False,
        },
    }


def build_claim_review(
    *,
    claim_id: str,
    claim_text: str,
    source_refs: Iterable[str],
    verified: bool,
    waiver_reason: str | None = None,
) -> dict[str, Any]:
    refs = [str(item) for item in source_refs if str(item).strip()]
    if verified and not refs:
        raise ValueError("verified claim requires source refs")
    if not verified and not refs and not str(waiver_reason or "").strip():
        raise ValueError("unverified claim requires source or waiver reason")
    return {
        "schema": "AgentTubeClaimReview/v1",
        "claim_id": str(claim_id),
        "claim_text": str(claim_text),
        "source_refs": refs,
        "verified_source_state": "VERIFIED" if verified else "UNVERIFIED",
        "waiver_reason": waiver_reason,
        "review_invalidated_on_claim_change": True,
        "gta6_brain_evidence_map_remains_authority": True,
    }


def build_shorts_candidate(
    *,
    parent_video_id: str,
    source_scene_ids: Iterable[str],
    source_timestamps: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": "AgentTubeShortsCandidate/v1",
        "status": "EXPERIMENTAL_DORMANT",
        "parent_video_id": str(parent_video_id),
        "source_scene_ids": list(source_scene_ids),
        "source_timestamps": list(source_timestamps),
        "provenance_inherited": True,
        "rights_inherited_subject_to_review": True,
        "independent_review_required": True,
        "auto_publish": False,
        "burned_subtitles": False,
        "open_captions": False,
        "transcript_overlay": False,
        "srt_burn_in": False,
    }


def build_engagement_evidence(*, comments: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        {
            "comment_id": str(item.get("comment_id") or ""),
            "text": str(item.get("text") or ""),
            "is_question": "?" in str(item.get("text") or ""),
        }
        for item in comments
        if isinstance(item, dict)
    ]
    return {
        "schema": "AgentTubeEngagementEvidence/v1",
        "mode": "READ_ONLY_DRAFT_ONLY",
        "comments": rows,
        "mutations_allowed": [],
        "comments_are_factual_evidence": False,
        "audience_topics_become": "ResearchCandidate",
        "verification_authority": "GTA6_BRAIN",
    }


def _production(input_payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": "AgentTubeProductionEvidence/v1",
        "render_pipeline_authority": "BR_NO_GTA",
        "localized_scene_repair_supported": True,
        "full_rebuild_when_unnecessary": 0,
    }
    if input_payload.get("scenes"):
        result["scene_manifest"] = build_scene_manifest(input_payload["scenes"])
    if input_payload.get("local_checks") is not None:
        result["readiness"] = build_production_readiness_evidence(
            local_checks=dict(input_payload.get("local_checks") or {}),
            paid_probes=input_payload.get("paid_probes") or (),
        )
    return result


def _publishing(input_payload: dict[str, Any]) -> dict[str, Any]:
    publication_id = input_payload.get("publication_id")
    if isinstance(publication_id, bool) or not isinstance(publication_id, int) or publication_id <= 0:
        raise ValueError("publishing capability requires positive publication_id")
    operation = str(input_payload.get("operation") or "prepare").strip().lower()
    if operation == "publish":
        if (
            input_payload.get("approval_source") != "user"
            or input_payload.get("approval_operation") != "br_youtube_pode_postar"
        ):
            raise PermissionError(
                "br_youtube_pode_postar(publication_id) explicit user approval is required"
            )
        return {
            "schema": "AgentTubePublishingDelegation/v1",
            "publication_id": publication_id,
            "publication_gate": "br_youtube_pode_postar",
            "publication_attempted": False,
            "delegation_target": (
                "app.services.harness_youtube_publication_service."
                "publish_targeted_publication"
            ),
            "status": "HARNESS_DELEGATION_REQUIRED",
            "fallback_allowed": False,
        }
    if operation != "prepare":
        raise ValueError("unsupported AgentTube publishing operation")
    return {
        "schema": "AgentTubePublishingPreparation/v1",
        "publication_id": publication_id,
        "publication_gate": "br_youtube_pode_postar",
        "publication_attempted": False,
        "status": "WAITING_HUMAN_GATE",
        "fallback_allowed": False,
    }


def _analytics(input_payload: dict[str, Any]) -> dict[str, Any]:
    manifest = input_payload.get("scene_manifest")
    curve = input_payload.get("retention_curve")
    if isinstance(manifest, dict) and curve is not None:
        retention = map_retention_to_scenes(
            manifest,
            curve,
            source_state=str(input_payload.get("source_state") or "UNKNOWN"),
        )
    else:
        retention = {
            "schema": "SceneRetentionEvidence/v1",
            "source_state": str(input_payload.get("source_state") or "UNKNOWN").upper(),
            "observations": [],
            "eligible_for_learning": False,
            "missing_is_zero": False,
        }
    return {
        "schema": "AgentTubeAnalyticsEvidence/v1",
        "retention": retention,
        "learning_promotion_authority": "LEARNING_PLANE",
        "auto_promote": False,
    }


_HANDLERS = {
    "youtube.content-strategy": _content_strategy,
    "youtube.script-writing": _script_writing,
    "youtube.thumbnail-design": _thumbnail_design,
    "youtube.discoverability": _discoverability,
    "youtube.production": _production,
    "youtube.publishing": _publishing,
    "youtube.analytics-learning": _analytics,
}


def execute_agenttube_capability(
    capability: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    capability_id = str(getattr(capability, "capability_id", "") or "").strip()
    specs = {spec.capability_id: spec for spec in agenttube_capability_specs()}
    spec = specs.get(capability_id)
    if spec is None:
        raise PermissionError("unknown AgentTube capability")
    envelope, requirement, input_payload = _validate_canonical_task(
        capability_id,
        payload,
    )
    result = _HANDLERS[capability_id](input_payload)
    return {
        "schema": RESULT_SCHEMA,
        "capability_id": capability_id,
        "task_id": envelope.task_id,
        "task_schema": envelope.schema,
        "requirement_schema": requirement.schema,
        "source_project": spec.source_project,
        "source_sha": spec.source_sha,
        "authority": "DEEPSEEK_HARNESS",
        "lumen_authority": 0,
        "second_control_plane": 0,
        "duplicate_task_framework": 0,
        "duplicate_learning_plane": 0,
        "external_side_effect_performed": False,
        "paid_side_effects": 0,
        "learning_promotion_performed": False,
        "returned_to_harness": True,
        "result": result,
    }
