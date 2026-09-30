from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EvidenceLinkedRecord:
    evidence_refs: tuple[str, ...] = ()
    authority: str = "DEEPSEEK_HARNESS"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class YouTubeCompetitorProfile(EvidenceLinkedRecord):
    channel_id: str = ""
    channel_name: str = ""
    market: str = ""
    segment: str = ""
    observed_at: str = ""
    source: str = "OFFICIAL_YOUTUBE_INTERFACE"
    schema: str = "YouTubeCompetitorProfile/v1"


@dataclass(frozen=True)
class CompetitorVideoObservation(EvidenceLinkedRecord):
    video_id: str = ""
    channel_id: str = ""
    title: str = ""
    published_at: str | None = None
    duration_seconds: int | None = None
    view_count: int | None = None
    framing: str = UNKNOWN
    promise_density: str = UNKNOWN
    transcript_ref: str | None = None
    comment_sample_ref: str | None = None
    schema: str = "CompetitorVideoObservation/v1"


@dataclass(frozen=True)
class AudienceDemandSignal(EvidenceLinkedRecord):
    signal_id: str = ""
    source_type: str = ""
    topic: str = ""
    market: str = ""
    strength: float | None = None
    freshness: str = UNKNOWN
    observed_at: str = ""
    schema: str = "AudienceDemandSignal/v1"


@dataclass(frozen=True)
class EditorialOpportunityCandidate(EvidenceLinkedRecord):
    opportunity_id: str = ""
    topic: str = ""
    trigger: str = ""
    target_audience: str = ""
    viewer_problem: str = ""
    demand_evidence: tuple[str, ...] = ()
    competition_evidence: tuple[str, ...] = ()
    content_gap: str = ""
    official_evidence_availability: str = UNKNOWN
    novelty: str = UNKNOWN
    timeliness: str = UNKNOWN
    expected_depth_minutes: float | None = None
    catalog_relationship: str = UNKNOWN
    monetization_risks: tuple[str, ...] = ()
    score_components: dict[str, Any] = field(default_factory=dict)
    schema: str = "EditorialOpportunityCandidate/v1"


@dataclass(frozen=True)
class VideoStrategyBrief(EvidenceLinkedRecord):
    video_id: str = ""
    opportunity_id: str = ""
    target_viewer: str = ""
    viewer_promise: str = ""
    core_question: str = ""
    primary_value: str = ""
    novelty: str = ""
    why_now: str = ""
    content_pillar: str = ""
    competitive_differentiation: str = ""
    expected_duration_minutes: float = 20.0
    search_intent: str = ""
    browse_intent: str = ""
    suggested_video_relationship: str = ""
    series: str | None = None
    next_video_path: str | None = None
    revenue_considerations: tuple[str, ...] = ()
    schema: str = "VideoStrategyBrief/v1"


@dataclass(frozen=True)
class HookContract(EvidenceLinkedRecord):
    title_promise: str = ""
    thumbnail_promise: str = ""
    first_spoken_promise: str = ""
    proof_of_value: str = ""
    stakes: str = ""
    novelty: str = ""
    first_visual_payoff: str = ""
    first_information_payoff: str = ""
    open_loop: str = ""
    expected_30s_behavior: str = ""
    schema: str = "HookContract/v1"


@dataclass(frozen=True)
class RetentionBlueprint(EvidenceLinkedRecord):
    video_id: str = ""
    hook: dict[str, Any] = field(default_factory=dict)
    first_value_timestamp_seconds: float = 0.0
    first_value_timestamp: float | None = None
    novelty_cadence_seconds: float | None = None
    open_loops: tuple[dict[str, Any], ...] = ()
    section_payoffs: tuple[dict[str, Any], ...] = ()
    novelty_cadence: tuple[dict[str, Any], ...] = ()
    visual_changes: tuple[dict[str, Any], ...] = ()
    evidence_reveals: tuple[dict[str, Any], ...] = ()
    story_progression: tuple[str, ...] = ()
    rehooks: tuple[dict[str, Any], ...] = ()
    cta_positions: tuple[dict[str, Any], ...] = ()
    ad_break_candidates: tuple[dict[str, Any], ...] = ()
    ending_payoff: str = ""
    end_screen_transition: str = ""
    schema: str = "RetentionBlueprint/v1"


@dataclass(frozen=True)
class PackagingVariantSet(EvidenceLinkedRecord):
    video_id: str = ""
    title_variants: tuple[dict[str, Any], ...] = ()
    thumbnail_variants: tuple[dict[str, Any], ...] = ()
    schema: str = "PackagingVariantSet/v1"


@dataclass(frozen=True)
class AdvertiserSuitabilityReview(EvidenceLinkedRecord):
    video_id: str = ""
    title_risk: str = UNKNOWN
    thumbnail_risk: str = UNKNOWN
    first_7s_risk: str = UNKNOWN
    first_30s_risk: str = UNKNOWN
    language_risk: str = UNKNOWN
    visual_violence_risk: str = UNKNOWN
    graphic_violence_risk: str = UNKNOWN
    sexual_content_risk: str = UNKNOWN
    drug_content_risk: str = UNKNOWN
    shock_content_risk: str = UNKNOWN
    hate_slur_risk: str = UNKNOWN
    expected_monetization_impact: str = UNKNOWN
    avoidable_risk_actions: tuple[str, ...] = ()
    categories: dict[str, str] = field(default_factory=dict)
    editorial_truth_preserved: bool = True
    schema: str = "AdvertiserSuitabilityReview/v1"


@dataclass(frozen=True)
class NaturalAdBreakCandidate(EvidenceLinkedRecord):
    video_id: str = ""
    timestamp_seconds: float = 0.0
    transition_type: str = ""
    rationale: str = ""
    reason: str | None = None
    immediate_promised_payoff_pending: bool = False
    before_immediate_payoff: bool = False
    mid_sentence: bool = False
    schema: str = "NaturalAdBreakCandidate/v1"


@dataclass(frozen=True)
class YouTubePerformanceSnapshot(EvidenceLinkedRecord):
    video_id: str = ""
    observation_window: str = ""
    observed_at: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    traffic_sources: tuple[dict[str, Any], ...] = ()
    dimensions: dict[str, Any] = field(default_factory=dict)
    source: str = "YOUTUBE_ANALYTICS_API"
    schema: str = "YouTubePerformanceSnapshot/v1"


@dataclass(frozen=True)
class RetentionEvent(EvidenceLinkedRecord):
    video_id: str = ""
    event_type: str = ""
    timestamp_seconds: float = 0.0
    script_section: str | None = None
    visual_section: str | None = None
    audio_section: str | None = None
    topic: str | None = None
    editing_pattern: str | None = None
    hypothesized_cause: str = UNKNOWN
    causal_status: str = "HYPOTHESIS"
    cause_status: str | None = None
    schema: str = "RetentionEvent/v1"


@dataclass(frozen=True)
class YouTubeRevenueSnapshot(EvidenceLinkedRecord):
    video_id: str = ""
    period_start: str = ""
    period_end: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    currency: str | None = None
    source_label: str = "YOUTUBE_REPORTED"
    schema: str = "YouTubeRevenueSnapshot/v1"


@dataclass(frozen=True)
class VideoPostmortem(EvidenceLinkedRecord):
    video_id: str = ""
    what_worked: tuple[str, ...] = ()
    what_failed: tuple[str, ...] = ()
    viewer_loss_events: tuple[str, ...] = ()
    rewatch_events: tuple[str, ...] = ()
    traffic_source_findings: tuple[str, ...] = ()
    packaging_assessment: str = UNKNOWN
    audience_exhaustion_assessment: str = UNKNOWN
    revenue_findings: tuple[str, ...] = ()
    advertiser_suitability_findings: tuple[str, ...] = ()
    comment_subscriber_findings: tuple[str, ...] = ()
    repeat_candidates: tuple[str, ...] = ()
    retire_candidates: tuple[str, ...] = ()
    causal_claims_verified: tuple[str, ...] = ()
    hypotheses: tuple[str, ...] = ()
    schema: str = "VideoPostmortem/v1"


@dataclass(frozen=True)
class VideoBusinessOutcome(EvidenceLinkedRecord):
    video_id: str = ""
    period_start: str = ""
    period_end: str = ""
    youtube_ad_revenue: float | None = None
    youtube_premium_revenue: float | None = None
    membership_attributed_revenue: float | None = None
    supers_revenue: float | None = None
    affiliate_revenue: float | None = None
    sponsor_revenue: float | None = None
    merchandise_revenue: float | None = None
    catalog_spillover_value: float | None = None
    audience_growth_value: float | None = None
    production_cost: float | None = None
    promotion_cost: float | None = None
    currency: str | None = None
    youtube_reported_revenue: float | None = None
    external_confirmed_revenue: float | None = None
    net_content_value: float | None = None
    unknown_terms: tuple[str, ...] = ()
    schema: str = "VideoBusinessOutcome/v1"

    def known_net_content_value(self) -> float | None:
        values = (
            self.youtube_ad_revenue,
            self.youtube_premium_revenue,
            self.membership_attributed_revenue,
            self.supers_revenue,
            self.affiliate_revenue,
            self.sponsor_revenue,
            self.merchandise_revenue,
            self.catalog_spillover_value,
            self.audience_growth_value,
        )
        costs = (self.production_cost, self.promotion_cost)
        known = [v for v in (*values, *costs) if v is not None]
        if not known:
            return None
        return sum(v for v in values if v is not None) - sum(v for v in costs if v is not None)


@dataclass(frozen=True)
class EditorialBeat(EvidenceLinkedRecord):
    beat_id: str = ""
    script_section_id: str = ""
    narrative_function: str = ""
    retention_risk: str = ""
    schema: str = "EditorialBeat/v1"


@dataclass(frozen=True)
class VisualBeat(EvidenceLinkedRecord):
    beat_id: str = ""
    editorial_beat_id: str = ""
    visual_evidence_ref: str | None = None
    b_roll: str | None = None
    pace: str = ""
    camera_motion: str | None = None
    graphic_requirement: str | None = None
    sound_design: str | None = None
    novelty_function: str = ""
    transition: str = ""
    schema: str = "VisualBeat/v1"


@dataclass(frozen=True)
class RetentionRisk(EvidenceLinkedRecord):
    risk_id: str = ""
    beat_id: str = ""
    risk_type: str = ""
    severity: str = ""
    mitigation: str = ""
    schema: str = "RetentionRisk/v1"


@dataclass(frozen=True)
class CatalogRelationship(EvidenceLinkedRecord):
    video_id: str = ""
    parent_series: str | None = None
    previous_episode: str | None = None
    next_logical_episode: str | None = None
    related_back_catalog: tuple[str, ...] = ()
    end_screen_target: str | None = None
    playlist: str | None = None
    schema: str = "CatalogRelationship/v1"


@dataclass(frozen=True)
class NextViewStrategy(EvidenceLinkedRecord):
    video_id: str = ""
    bridge_reason: str = ""
    target_video_id: str = ""
    end_screen_window_seconds: float = 20.0
    schema: str = "NextViewStrategy/v1"


@dataclass(frozen=True)
class YouTubeExperiment(EvidenceLinkedRecord):
    experiment_id: str = ""
    video_id: str = ""
    surface: str = ""
    control: dict[str, Any] = field(default_factory=dict)
    challenger: dict[str, Any] = field(default_factory=dict)
    result_class: str = "INCONCLUSIVE"
    native_experiment: bool = False
    schema: str = "YouTubeExperiment/v1"


@dataclass(frozen=True)
class YouTubePackagingExperiment(EvidenceLinkedRecord):
    video_id: str = ""
    variants: tuple[dict[str, Any], ...] = ()
    experiment_start: str = ""
    experiment_end: str | None = None
    native_result: str = "INCONCLUSIVE"
    watch_time_share_winner: str | None = None
    confidence_class: str = "INCONCLUSIVE"
    schema: str = "YouTubePackagingExperiment/v1"


@dataclass(frozen=True)
class EditorialGapMap(EvidenceLinkedRecord):
    topic: str = ""
    market: str = ""
    competitor_coverage: tuple[str, ...] = ()
    missing_angles: tuple[str, ...] = ()
    br_specific_gaps: tuple[str, ...] = ()
    observed_at: str = ""
    schema: str = "EditorialGapMap/v1"


@dataclass(frozen=True)
class BRNoGTAEditorialMoat(EvidenceLinkedRecord):
    positioning: str = "BRAZILIAN GTA VI INVESTIGATIVE ENTERTAINMENT"
    strengths: tuple[str, ...] = ()
    non_negotiables: tuple[str, ...] = ()
    validated_by: tuple[str, ...] = ()
    status: str = "CANDIDATE"
    schema: str = "BRNoGTAEditorialMoat/v1"


@dataclass(frozen=True)
class YouTubePublicationSpec(EvidenceLinkedRecord):
    video_id: str = ""
    master_artifact_sha: str = ""
    title: str = ""
    description: str = ""
    thumbnail_ref: str = ""
    language: str = "pt-BR"
    category: str | None = None
    playlist: str | None = None
    series: str | None = None
    chapters: tuple[dict[str, Any], ...] = ()
    privacy: str = "PRIVATE"
    publish_at: str | None = None
    monetization_intent: str = "UNKNOWN"
    contains_synthetic_media: bool | None = None
    related_videos: tuple[str, ...] = ()
    end_screen_plan: dict[str, Any] = field(default_factory=dict)
    cards_plan: tuple[dict[str, Any], ...] = ()
    comment_strategy: dict[str, Any] = field(default_factory=dict)
    human_approval_ref: str | None = None
    schema: str = "YouTubePublicationSpec/v1"


@dataclass(frozen=True)
class VideoEditingLearningEpisode(EvidenceLinkedRecord):
    episode_id: str = ""
    video_id: str = ""
    source_performance_snapshot_refs: tuple[str, ...] = ()
    retention_event_refs: tuple[str, ...] = ()
    edit_decision_refs: tuple[str, ...] = ()
    verified_patterns: tuple[str, ...] = ()
    hypotheses: tuple[str, ...] = ()
    schema: str = "VideoEditingLearningEpisode/v1"


@dataclass(frozen=True)
class AudienceQuestionCluster(EvidenceLinkedRecord):
    cluster_id: str = ""
    topic: str = ""
    question_count: int = 0
    representative_comment_refs: tuple[str, ...] = ()
    next_video_demand: bool = False
    schema: str = "AudienceQuestionCluster/v1"


@dataclass(frozen=True)
class AudienceComplaintCluster(EvidenceLinkedRecord):
    cluster_id: str = ""
    topic: str = ""
    complaint_count: int = 0
    representative_comment_refs: tuple[str, ...] = ()
    category: str = "UNKNOWN"
    schema: str = "AudienceComplaintCluster/v1"


@dataclass(frozen=True)
class AudiencePraiseCluster(EvidenceLinkedRecord):
    cluster_id: str = ""
    topic: str = ""
    praise_count: int = 0
    representative_comment_refs: tuple[str, ...] = ()
    category: str = "UNKNOWN"
    schema: str = "AudiencePraiseCluster/v1"


@dataclass(frozen=True)
class AffiliateOpportunity(EvidenceLinkedRecord):
    opportunity_id: str = ""
    video_id: str = ""
    product_or_service: str = ""
    viewer_relevance: str = ""
    actual_product_relevance: str = ""
    disclosure_required: bool = True
    policy_compatible: bool = False
    schema: str = "AffiliateOpportunity/v1"


@dataclass(frozen=True)
class SponsorFitCandidate(EvidenceLinkedRecord):
    candidate_id: str = ""
    video_id: str = ""
    sponsor_name: str = ""
    audience_relevance: str = ""
    brand_safety: str = ""
    topic_fit: str = ""
    integration_naturalness: str = ""
    rate_or_value: str = "UNKNOWN"
    audience_trust_risk: str = "UNKNOWN"
    schema: str = "SponsorFitCandidate/v1"
