from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from typing import Any, Iterable

from app.contracts.youtube_intelligence_contracts import (
    AdvertiserSuitabilityReview,
    AudienceDemandSignal,
    CompetitorVideoObservation,
    EditorialOpportunityCandidate,
    HookContract,
    NaturalAdBreakCandidate,
    PackagingVariantSet,
    RetentionBlueprint,
    RetentionEvent,
    VideoBusinessOutcome,
    VideoPostmortem,
    VideoStrategyBrief,
    YouTubeCompetitorProfile,
    YouTubePerformanceSnapshot,
    YouTubeRevenueSnapshot,
)
from app.database.youtube_intelligence_repository import persist_intelligence_record


ALLOWED_RETENTION_EVENTS = {
    "INTRO_LOSS",
    "DIP",
    "SPIKE",
    "TOP_MOMENT",
    "GRADUAL_DECAY",
}

OBSERVATION_WINDOWS = {"1h", "6h", "24h", "48h", "7d", "28d", "90d"}


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _require_evidence(record: Any) -> None:
    refs = tuple(getattr(record, "evidence_refs", ()) or ())
    if not refs:
        raise ValueError(f"{record.__class__.__name__} requires evidence_refs")
    if getattr(record, "authority", None) != "DEEPSEEK_HARNESS":
        raise PermissionError("YouTube intelligence record escaped DeepSeek Harness authority")


def persist_typed_record(
    record: Any,
    *,
    subject_type: str,
    subject_id: str,
    source_system: str,
    period_start: str | None = None,
    period_end: str | None = None,
    retrieved_at: str | None = None,
    revision: int = 1,
    supersedes_record_id: str | None = None,
) -> dict[str, Any]:
    _require_evidence(record)
    payload = asdict(record)
    schema_name = str(payload.get("schema") or "")
    if not schema_name:
        raise ValueError("typed YouTube intelligence record requires schema")
    record_id = f"ytintel-{_digest({'schema':schema_name,'subject_type':subject_type,'subject_id':subject_id,'payload':payload})[:24]}"
    persisted,_ = persist_intelligence_record(
        record_id=record_id,
        schema_name=schema_name,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
        source_system=source_system,
        evidence_refs=list(record.evidence_refs),
        period_start=period_start,
        period_end=period_end,
        retrieved_at=retrieved_at,
        revision=revision,
        supersedes_record_id=supersedes_record_id,
        authority=record.authority,
    )
    return persisted


def validate_competitor_profile(record: YouTubeCompetitorProfile) -> None:
    _require_evidence(record)
    if not record.channel_id or not record.channel_name:
        raise ValueError("competitor profile requires channel identity")
    if record.market not in {"BRAZIL", "GLOBAL", "OTHER"}:
        raise ValueError("competitor profile market must be BRAZIL/GLOBAL/OTHER")
    if not record.segment:
        raise ValueError("competitor profile requires segment")


def validate_competitor_video(record: CompetitorVideoObservation) -> None:
    _require_evidence(record)
    if not record.video_id or not record.channel_id or not record.title:
        raise ValueError("competitor video requires exact video/channel identity")
    if record.duration_seconds is not None and record.duration_seconds < 0:
        raise ValueError("competitor video duration cannot be negative")
    if record.view_count is not None and record.view_count < 0:
        raise ValueError("competitor video views cannot be negative")


def validate_demand_signal(record: AudienceDemandSignal) -> None:
    _require_evidence(record)
    if not record.signal_id or not record.topic or not record.source_type:
        raise ValueError("demand signal identity/topic/source required")
    if record.strength is not None and not 0.0 <= record.strength <= 1.0:
        raise ValueError("demand signal strength must be [0,1] or UNKNOWN")


def build_editorial_opportunity(
    *,
    opportunity_id: str,
    topic: str,
    trigger: str,
    target_audience: str,
    viewer_problem: str,
    demand_evidence: Iterable[str],
    competition_evidence: Iterable[str],
    content_gap: str,
    official_evidence_availability: str,
    novelty: str,
    timeliness: str,
    expected_depth_minutes: float | None,
    catalog_relationship: str,
    monetization_risks: Iterable[str],
    evidence_refs: Iterable[str],
) -> EditorialOpportunityCandidate:
    demand=tuple(dict.fromkeys(str(x) for x in demand_evidence if str(x)))
    competition=tuple(dict.fromkeys(str(x) for x in competition_evidence if str(x)))
    refs=tuple(dict.fromkeys(str(x) for x in evidence_refs if str(x)))
    if not demand or not competition or not refs:
        raise ValueError("opportunity requires demand, competition and evidence refs")
    if expected_depth_minutes is not None and expected_depth_minutes < 20:
        raise ValueError("BR-no-GTA opportunity does not support the 20-minute final gate")
    if official_evidence_availability not in {"STRONG", "SUFFICIENT", "LIMITED", "UNKNOWN"}:
        raise ValueError("invalid official evidence availability")
    return EditorialOpportunityCandidate(
        opportunity_id=opportunity_id,
        topic=topic,
        trigger=trigger,
        target_audience=target_audience,
        viewer_problem=viewer_problem,
        demand_evidence=demand,
        competition_evidence=competition,
        content_gap=content_gap,
        official_evidence_availability=official_evidence_availability,
        novelty=novelty,
        timeliness=timeliness,
        expected_depth_minutes=expected_depth_minutes,
        catalog_relationship=catalog_relationship,
        monetization_risks=tuple(monetization_risks),
        evidence_refs=refs,
    )


def validate_strategy_brief(record: VideoStrategyBrief) -> None:
    _require_evidence(record)
    if record.expected_duration_minutes < 20:
        raise ValueError("VideoStrategyBrief must preserve >=20 minute final-video gate")
    for value,name in (
        (record.target_viewer,"target_viewer"),
        (record.viewer_promise,"viewer_promise"),
        (record.core_question,"core_question"),
        (record.primary_value,"primary_value"),
        (record.competitive_differentiation,"competitive_differentiation"),
    ):
        if not str(value).strip():
            raise ValueError(f"VideoStrategyBrief missing {name}")


def validate_hook_contract(record: HookContract) -> None:
    _require_evidence(record)
    required = {
        "title_promise": record.title_promise,
        "thumbnail_promise": record.thumbnail_promise,
        "first_spoken_promise": record.first_spoken_promise,
        "proof_of_value": record.proof_of_value,
        "first_visual_payoff": record.first_visual_payoff,
        "first_information_payoff": record.first_information_payoff,
        "expected_30s_behavior": record.expected_30s_behavior,
    }
    missing=[k for k,v in required.items() if not str(v).strip()]
    if missing:
        raise ValueError("HookContract missing: " + ",".join(missing))


def validate_retention_blueprint(record: RetentionBlueprint) -> None:
    _require_evidence(record)
    if record.first_value_timestamp_seconds < 0:
        raise ValueError("first value timestamp cannot be negative")
    if record.first_value_timestamp_seconds > 60:
        raise ValueError("branding/value design violates first-minute value requirement")
    if not record.ending_payoff or not record.end_screen_transition:
        raise ValueError("retention blueprint requires designed ending and end-screen transition")


def validate_packaging_variants(record: PackagingVariantSet) -> None:
    _require_evidence(record)
    if len(record.title_variants) < 3 or len(record.thumbnail_variants) < 3:
        raise ValueError("major video packaging requires >=3 title and >=3 thumbnail variants")
    for variant in (*record.title_variants, *record.thumbnail_variants):
        if not isinstance(variant, dict):
            raise ValueError("packaging variant must be object")
        required={"target_audience","promise","expected_weakness"}
        if not required.issubset(variant):
            raise ValueError("packaging variant lacks required evaluation fields")


def validate_ad_break_candidate(record: NaturalAdBreakCandidate) -> None:
    _require_evidence(record)
    if record.timestamp_seconds < 0:
        raise ValueError("ad break timestamp cannot be negative")
    if record.mid_sentence:
        raise PermissionError("planned mid-roll cannot be mid-sentence")
    if record.immediate_promised_payoff_pending:
        raise PermissionError("planned mid-roll cannot interrupt immediate promised payoff")
    if record.transition_type not in {"SECTION_TRANSITION","AUDIO_PAUSE","VISUAL_TRANSITION","COMPLETED_PAYOFF"}:
        raise ValueError("ad break must use a natural transition type")


def validate_performance_snapshot(record: YouTubePerformanceSnapshot) -> None:
    _require_evidence(record)
    if record.observation_window not in OBSERVATION_WINDOWS:
        raise ValueError("unsupported YouTube performance observation window")
    if "ctr" in record.metrics and "impressions" not in record.metrics:
        raise ValueError("CTR cannot be interpreted without impressions")
    if "ctr" in record.metrics and not record.traffic_sources:
        raise ValueError("CTR snapshot requires traffic-source context")


def validate_revenue_snapshot(record: YouTubeRevenueSnapshot) -> None:
    _require_evidence(record)
    if record.source_label != "YOUTUBE_REPORTED":
        raise ValueError("YouTubeRevenueSnapshot source must be YOUTUBE_REPORTED")
    for key,value in record.metrics.items():
        if isinstance(value, dict) and value.get("status") == "UNKNOWN":
            continue
        if value is None:
            continue
        if isinstance(value, (int,float)) and value < 0 and key not in {"subscribersLost"}:
            raise ValueError(f"revenue metric {key} cannot be negative")


def validate_retention_event(record: RetentionEvent) -> None:
    _require_evidence(record)
    if record.event_type not in ALLOWED_RETENTION_EVENTS:
        raise ValueError("invalid retention event type")
    if record.timestamp_seconds < 0:
        raise ValueError("retention event timestamp cannot be negative")
    if record.causal_status not in {"HYPOTHESIS","SUPPORTED","VERIFIED","CONTRADICTED"}:
        raise ValueError("invalid retention causal status")
    if record.causal_status == "HYPOTHESIS" and record.hypothesized_cause == "":
        raise ValueError("retention hypothesis must name a hypothesized cause or UNKNOWN")


def validate_postmortem(record: VideoPostmortem) -> None:
    _require_evidence(record)
    if not record.what_worked and not record.what_failed:
        raise ValueError("postmortem requires observed outcomes")
    if set(record.causal_claims_verified).intersection(record.hypotheses):
        raise ValueError("verified causes and hypotheses must remain separated")


def evaluate_business_outcome(record: VideoBusinessOutcome) -> dict[str, Any]:
    _require_evidence(record)
    net = record.known_net_content_value()
    unknown = [
        field
        for field in (
            "youtube_ad_revenue",
            "youtube_premium_revenue",
            "membership_attributed_revenue",
            "supers_revenue",
            "affiliate_revenue",
            "sponsor_revenue",
            "merchandise_revenue",
            "catalog_spillover_value",
            "audience_growth_value",
            "production_cost",
            "promotion_cost",
        )
        if getattr(record, field) is None
    ]
    return {
        "schema": "VideoBusinessOutcomeEvaluation/v1",
        "video_id": record.video_id,
        "known_net_content_value": net,
        "currency": record.currency,
        "unknown_components": unknown,
        "complete": not unknown,
        "objective": "MAXIMIZE_SUSTAINABLE_PROFIT_SUBJECT_TO_EDITORIAL_AND_HUMAN_GATES",
        "evidence_refs": list(record.evidence_refs),
    }
