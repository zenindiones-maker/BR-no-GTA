from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from app.contracts.youtube_intelligence_contracts import (
    EditorialOpportunityCandidate,
    VideoBusinessOutcome,
    VideoStrategyBrief,
)


OPPORTUNITY_COMPONENTS=(
    "demand",
    "competition",
    "freshness",
    "br_audience_relevance",
    "available_evidence",
    "supported_20m_depth",
    "novelty",
    "monetization_suitability",
    "catalog_fit",
)


def _component(value: Any) -> dict[str,Any]:
    if value is None or value=="UNKNOWN":
        return {"status":"UNKNOWN","value":None}
    numeric=float(value)
    if numeric < 0 or numeric > 1:
        raise ValueError("opportunity components must be normalized to [0,1]")
    return {"status":"VALUE","value":numeric}


def build_editorial_opportunity(
    *,
    opportunity_id: str,
    topic: str,
    trigger: str,
    target_audience: str,
    viewer_problem: str,
    demand_evidence: Sequence[str],
    competition_evidence: Sequence[str],
    content_gap: str,
    official_evidence_availability: str,
    expected_depth_minutes: float | None,
    catalog_relationship: str,
    monetization_risks: Sequence[str],
    components: Mapping[str,Any],
    evidence_refs: Sequence[str],
) -> EditorialOpportunityCandidate:
    if expected_depth_minutes is not None and float(expected_depth_minutes) < 20.0:
        raise ValueError("opportunity must support the 20+ minute final-video gate")
    normalized={name:_component(components.get(name)) for name in OPPORTUNITY_COMPONENTS}
    known=[row["value"] for row in normalized.values() if row["status"]=="VALUE"]
    composite=None
    score_state="UNKNOWN"
    if len(known)==len(OPPORTUNITY_COMPONENTS):
        # Competition is inverse: lower competition contributes positively.
        weights={
            "demand":0.19,"competition":0.10,"freshness":0.11,
            "br_audience_relevance":0.12,"available_evidence":0.12,
            "supported_20m_depth":0.12,"novelty":0.09,
            "monetization_suitability":0.07,"catalog_fit":0.08,
        }
        composite=sum(
            weights[name] * (
                1.0-normalized[name]["value"]
                if name=="competition"
                else normalized[name]["value"]
            )
            for name in OPPORTUNITY_COMPONENTS
        )
        score_state="VALUE"
    score_components={
        "schema":"EditorialOpportunityScoring/v1",
        "components":normalized,
        "composite_status":score_state,
        "composite_score":composite,
        "trend_alone_is_opportunity":False,
        "ranking_allowed":score_state=="VALUE",
    }
    return EditorialOpportunityCandidate(
        opportunity_id=opportunity_id,
        topic=topic,
        trigger=trigger,
        target_audience=target_audience,
        viewer_problem=viewer_problem,
        demand_evidence=tuple(demand_evidence),
        competition_evidence=tuple(competition_evidence),
        content_gap=content_gap,
        official_evidence_availability=official_evidence_availability,
        novelty=normalized["novelty"]["value"],
        timeliness=normalized["freshness"]["value"],
        expected_depth_minutes=expected_depth_minutes,
        catalog_relationship=catalog_relationship,
        monetization_risks=tuple(monetization_risks),
        score_components=score_components,
        evidence_refs=tuple(evidence_refs),
    )


def build_video_strategy_brief(
    *,
    opportunity: EditorialOpportunityCandidate,
    target_viewer: str,
    viewer_promise: str,
    core_question: str,
    primary_value: str,
    novelty: str,
    why_now: str,
    content_pillar: str,
    competitive_differentiation: str,
    expected_duration_minutes: float,
    search_intent: str,
    browse_intent: str,
    suggested_video_relationship: str,
    series: str | None,
    next_video_path: str,
    revenue_considerations: Sequence[str],
) -> VideoStrategyBrief:
    if not viewer_promise.strip():
        raise ValueError("no video may proceed without a viewer promise")
    return VideoStrategyBrief(
        opportunity_id=opportunity.opportunity_id,
        target_viewer=target_viewer,
        viewer_promise=viewer_promise,
        core_question=core_question,
        primary_value=primary_value,
        novelty=novelty,
        why_now=why_now,
        content_pillar=content_pillar,
        competitive_differentiation=competitive_differentiation,
        expected_duration_minutes=expected_duration_minutes,
        search_intent=search_intent,
        browse_intent=browse_intent,
        suggested_video_relationship=suggested_video_relationship,
        series=series,
        next_video_path=next_video_path,
        revenue_considerations=tuple(revenue_considerations),
        evidence_refs=opportunity.evidence_refs,
    )


def calculate_video_business_outcome(
    *,
    video_id: str,
    youtube_reported_revenue: float | None,
    external_confirmed_revenue: float | None,
    production_cost: float | None,
    promotion_cost: float | None,
    catalog_spillover_value: float | None,
    audience_growth_value: float | None,
    evidence_refs: Sequence[str],
) -> VideoBusinessOutcome:
    values={
        "youtube_reported_revenue":youtube_reported_revenue,
        "external_confirmed_revenue":external_confirmed_revenue,
        "production_cost":production_cost,
        "promotion_cost":promotion_cost,
        "catalog_spillover_value":catalog_spillover_value,
        "audience_growth_value":audience_growth_value,
    }
    unknown=tuple(name for name,value in values.items() if value is None)
    net=None
    if not unknown:
        net=(
            float(youtube_reported_revenue)
            + float(external_confirmed_revenue)
            + float(catalog_spillover_value)
            + float(audience_growth_value)
            - float(production_cost)
            - float(promotion_cost)
        )
    return VideoBusinessOutcome(
        video_id=video_id,
        youtube_reported_revenue=youtube_reported_revenue,
        external_confirmed_revenue=external_confirmed_revenue,
        production_cost=production_cost,
        promotion_cost=promotion_cost,
        catalog_spillover_value=catalog_spillover_value,
        audience_growth_value=audience_growth_value,
        net_content_value=net,
        unknown_terms=unknown,
        evidence_refs=tuple(evidence_refs),
    )
