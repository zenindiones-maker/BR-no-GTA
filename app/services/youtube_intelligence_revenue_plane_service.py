from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping, Sequence


PLANE_SCHEMA="YouTubeIntelligenceAndRevenuePlane/v1"
AUTHORITY="DEEPSEEK_HARNESS"

CLOSED_LOOP_STAGES=(
    "MARKET",
    "AUDIENCE_DEMAND",
    "OPPORTUNITY",
    "CONTENT_STRATEGY",
    "GTA_VI_EVIDENCE",
    "SCRIPT",
    "RETENTION_DESIGN",
    "VIDEO_EDIT",
    "PACKAGING",
    "MASTER_QA",
    "PRIVATE_YOUTUBE_REVIEW",
    "HUMAN_PASS",
    "PUBLICATION",
    "DISTRIBUTION",
    "ANALYTICS",
    "REVENUE",
    "POSTMORTEM",
    "HARNESS_LEARNING",
    "NEXT_OPPORTUNITY",
)


@dataclass(frozen=True)
class YouTubeIntelligenceAndRevenuePlane:
    video_or_opportunity_id: str
    stage_evidence: Mapping[str,tuple[str,...]]
    current_stage: str
    authority: str=AUTHORITY
    second_control_plane: bool=False
    schema: str=PLANE_SCHEMA

    def __post_init__(self) -> None:
        if self.authority != AUTHORITY:
            raise PermissionError("YouTube intelligence plane cannot replace DeepSeek Harness")
        if self.second_control_plane:
            raise PermissionError("YouTube intelligence plane is not a control plane")
        if self.current_stage not in CLOSED_LOOP_STAGES:
            raise ValueError("unknown closed-loop stage")
        normalized={}
        for stage,refs in dict(self.stage_evidence).items():
            if stage not in CLOSED_LOOP_STAGES:
                raise ValueError(f"unknown stage evidence: {stage}")
            normalized[stage]=tuple(
                dict.fromkeys(str(ref).strip() for ref in refs if str(ref).strip())
            )
        object.__setattr__(self,"stage_evidence",normalized)

    def to_dict(self) -> dict[str,Any]:
        return asdict(self)


def validate_closed_loop_progression(
    stage_evidence: Mapping[str,Sequence[str]],
    *,
    through_stage: str,
) -> dict[str,Any]:
    if through_stage not in CLOSED_LOOP_STAGES:
        raise ValueError("invalid through_stage")
    index=CLOSED_LOOP_STAGES.index(through_stage)
    required=CLOSED_LOOP_STAGES[:index+1]
    missing=[
        stage
        for stage in required
        if not tuple(
            str(ref).strip()
            for ref in stage_evidence.get(stage,())
            if str(ref).strip()
        )
    ]
    return {
        "schema":"YouTubeClosedLoopEvidenceValidation/v1",
        "through_stage":through_stage,
        "required_stages":list(required),
        "missing_evidence_stages":missing,
        "status":"PASS" if not missing else "INCOMPLETE",
        "authority":AUTHORITY,
        "second_control_plane":False,
    }


def build_plane_snapshot(
    *,
    video_or_opportunity_id: str,
    stage_evidence: Mapping[str,Sequence[str]],
    current_stage: str,
) -> YouTubeIntelligenceAndRevenuePlane:
    validation=validate_closed_loop_progression(
        stage_evidence,
        through_stage=current_stage,
    )
    if validation["status"]!="PASS":
        raise ValueError(
            "closed-loop stage evidence incomplete: "
            + ",".join(validation["missing_evidence_stages"])
        )
    return YouTubeIntelligenceAndRevenuePlane(
        video_or_opportunity_id=str(video_or_opportunity_id),
        stage_evidence={
            stage:tuple(refs)
            for stage,refs in stage_evidence.items()
        },
        current_stage=current_stage,
    )


def build_acceptance_snapshot(
    *,
    internal_gates: Mapping[str,bool],
    external_gates: Mapping[str,str],
) -> dict[str,Any]:
    """Separate implemented/proven internal contracts from live external truth.

    External gates may only be PASS when an observed live receipt/evidence exists.
    This function never upgrades configuration-required or unproven states.
    """
    internal={
        str(key):("PASS" if bool(value) else "FAIL")
        for key,value in internal_gates.items()
    }
    allowed_external_states={
        "PASS",
        "NOT_YET_PROVEN",
        "EXTERNAL_CONFIGURATION_REQUIRED",
        "NOT_ELIGIBLE",
        "STUDIO_ONLY_SIGNAL",
    }
    external={}
    for key,value in external_gates.items():
        state=str(value)
        if state not in allowed_external_states:
            raise ValueError(f"invalid external gate state for {key}: {state}")
        external[str(key)]=state
    return {
        "schema":"YouTubeIntelligenceAcceptanceSnapshot/v1",
        "authority":AUTHORITY,
        "internal_contract_gates":internal,
        "external_runtime_gates":external,
        "all_internal_pass":all(value=="PASS" for value in internal.values()),
        "live_external_complete":all(value=="PASS" for value in external.values()),
        "no_external_truth_fabrication":True,
    }
