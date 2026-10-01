from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import sqrt
from typing import Any, Sequence


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _wilson_lower_bound(successes: int, total: int, *, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    successes=max(0,min(total,int(successes)))
    p=successes/total
    z2=z*z
    denominator=1.0+z2/total
    centre=p+z2/(2.0*total)
    margin=z*sqrt((p*(1.0-p)+z2/(4.0*total))/total)
    return max(0.0,(centre-margin)/denominator)


@dataclass(frozen=True)
class CompetenceIdentity:
    worker_id: str
    capability_id: str
    task_class: str
    worker_version: str
    model_version: str
    runtime_version: str
    schema: str="CompetenceIdentity/v1"


@dataclass(frozen=True)
class ConfidenceAwareCompetence:
    identity: CompetenceIdentity
    sample_count: int
    raw_verified_success_rate: float
    confidence_adjusted_success: float
    review_accept_rate: float
    human_correction_rate: float
    critical_regression_rate: float
    tool_efficiency: float
    context_efficiency: float
    mean_latency_ms: float
    freshness: float
    failure_profile: tuple[str,...]
    evidence_refs: tuple[str,...]
    content_sha256: str
    schema: str="ConfidenceAwareCompetence/v1"

    def to_dict(self)->dict[str,Any]:
        value=asdict(self)
        value["identity"]=asdict(self.identity)
        return value


def build_confidence_aware_competence(
    *,
    identity: CompetenceIdentity,
    sample_count: int,
    verified_success_count: int,
    review_accept_count: int,
    human_correction_count: int,
    critical_regression_count: int,
    tool_calls_total: int,
    context_bytes_total: int,
    latency_ms_total: int,
    freshness: float,
    failure_profile: Sequence[str],
    evidence_refs: Sequence[str],
) -> ConfidenceAwareCompetence:
    if sample_count <= 0:
        raise ValueError("sample_count must be positive")
    counts=(verified_success_count,review_accept_count,human_correction_count,critical_regression_count)
    if any(v < 0 or v > sample_count for v in counts):
        raise ValueError("competence counts must be within sample_count")
    if min(tool_calls_total,context_bytes_total,latency_ms_total) < 0:
        raise ValueError("efficiency totals must be non-negative")
    freshness=max(0.0,min(1.0,float(freshness)))
    raw=verified_success_count/sample_count
    wilson=_wilson_lower_bound(verified_success_count,sample_count)
    # Keep the established planner's Wilson small-sample protection and add
    # freshness as a multiplicative evidence-quality factor.
    adjusted=wilson*(0.75+0.25*freshness)
    base={
        "identity":asdict(identity),
        "sample_count":sample_count,
        "raw_verified_success_rate":round(raw,6),
        "confidence_adjusted_success":round(adjusted,6),
        "review_accept_rate":round(review_accept_count/sample_count,6),
        "human_correction_rate":round(human_correction_count/sample_count,6),
        "critical_regression_rate":round(critical_regression_count/sample_count,6),
        "tool_efficiency":round(sample_count/max(1,tool_calls_total),6),
        "context_efficiency":round(sample_count/max(1,context_bytes_total),9),
        "mean_latency_ms":round(latency_ms_total/sample_count,3),
        "freshness":round(freshness,6),
        "failure_profile":tuple(str(x) for x in failure_profile),
        "evidence_refs":tuple(str(x) for x in evidence_refs),
        "schema":"ConfidenceAwareCompetence/v1",
    }
    digest=sha256(_canonical_bytes(base)).hexdigest()
    return ConfidenceAwareCompetence(
        identity=identity,
        sample_count=sample_count,
        raw_verified_success_rate=base["raw_verified_success_rate"],
        confidence_adjusted_success=base["confidence_adjusted_success"],
        review_accept_rate=base["review_accept_rate"],
        human_correction_rate=base["human_correction_rate"],
        critical_regression_rate=base["critical_regression_rate"],
        tool_efficiency=base["tool_efficiency"],
        context_efficiency=base["context_efficiency"],
        mean_latency_ms=base["mean_latency_ms"],
        freshness=base["freshness"],
        failure_profile=base["failure_profile"],
        evidence_refs=base["evidence_refs"],
        content_sha256=digest,
    )


def select_competence_candidate(
    *,
    candidates: Sequence[ConfidenceAwareCompetence],
    required_capability_id: str,
    required_task_class: str,
    required_worker_version: str|None,
    required_model_version: str|None,
    required_runtime_version: str|None,
    eligible_worker_ids: Sequence[str],
) -> ConfidenceAwareCompetence:
    # HARD ELIGIBILITY is deliberately a filter, never a score term.
    eligible=set(eligible_worker_ids)
    rows=[
        row for row in candidates
        if row.identity.worker_id in eligible
        and row.identity.capability_id==required_capability_id
        and row.identity.task_class==required_task_class
        and row.critical_regression_rate==0.0
    ]
    if required_worker_version is not None:
        rows=[r for r in rows if r.identity.worker_version==required_worker_version]
    if required_model_version is not None:
        rows=[r for r in rows if r.identity.model_version==required_model_version]
    if required_runtime_version is not None:
        rows=[r for r in rows if r.identity.runtime_version==required_runtime_version]
    if not rows:
        raise LookupError("NO_HARD_ELIGIBLE_COMPETENCE_CANDIDATE")
    rows.sort(key=lambda r:(
        -r.confidence_adjusted_success,
        -r.freshness,
        -r.review_accept_rate,
        r.human_correction_rate,
        r.mean_latency_ms,
        -r.tool_efficiency,
        -r.context_efficiency,
        r.identity.worker_id,
    ))
    return rows[0]


__all__=[
    "CompetenceIdentity",
    "ConfidenceAwareCompetence",
    "build_confidence_aware_competence",
    "select_competence_candidate",
]
