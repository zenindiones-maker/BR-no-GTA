from __future__ import annotations

from typing import Any, Sequence

from app.contracts.youtube_intelligence_contracts import (
    ChannelOriginalityPolicy,
    MetricEvidenceClass,
    SyntheticMediaDisclosureDecision,
    VideoOriginalityReview,
    YouTubeOperationSurface,
)
from app.services.youtube_policy_registry_service import (
    current_policy_snapshot,
    policy_ref,
)


METRIC_EVIDENCE_CLASSES = {
    "OWNED_PRIVATE_METRIC",
    "PUBLIC_OFFICIAL_METRIC",
    "THIRD_PARTY_PROVIDER",
    "HUMAN_SUPPLIED",
    "INFERRED",
    "UNKNOWN",
}

COMPETITOR_PUBLIC_OFFICIAL_METRICS = {
    "viewCount",
    "likeCount",
    "commentCount",
    "subscriberCount",
    "publishedAt",
    "duration",
}

COMPETITOR_PRIVATE_METRICS = {
    "audienceWatchRatio",
    "relativeRetentionPerformance",
    "elapsedVideoTimeRatio",
    "estimatedRevenue",
    "estimatedAdRevenue",
    "monetizedPlaybacks",
    "cpm",
    "playbackBasedCpm",
    "videoThumbnailImpressions",
    "videoThumbnailImpressionsClickRate",
    "subscribersGained",
    "subscribersLost",
}


def classify_metric_evidence(
    *,
    metric_name: str,
    subject_scope: str,
    source_system: str,
    observed_at: str,
    source_ref: str,
    provider: str | None = None,
    retrieval_method: str | None = None,
    compliance_status: str | None = None,
    confidence: str = "HIGH",
) -> MetricEvidenceClass:
    metric = str(metric_name or "").strip()
    scope = str(subject_scope or "").strip().upper()
    source = str(source_system or "").strip().upper()
    if not metric or not scope or not source or not observed_at or not source_ref:
        raise ValueError("metric provenance identity is required")

    if source == "THIRD_PARTY":
        if not provider or not retrieval_method or not compliance_status:
            raise ValueError(
                "third-party metric provenance requires provider, retrieval method, and compliance status"
            )
        evidence_class = "THIRD_PARTY_PROVIDER"
    elif source in {"HUMAN", "HUMAN_SUPPLIED"}:
        evidence_class = "HUMAN_SUPPLIED"
    elif source == "INFERRED":
        evidence_class = "INFERRED"
    elif scope.startswith("OWNED_") and source in {
        "YOUTUBE_ANALYTICS_API",
        "YOUTUBE_REPORTING_API",
        "YOUTUBE_DATA_API_V3",
    }:
        evidence_class = (
            "OWNED_PRIVATE_METRIC"
            if source in {"YOUTUBE_ANALYTICS_API", "YOUTUBE_REPORTING_API"}
            else "PUBLIC_OFFICIAL_METRIC"
        )
    elif scope.startswith("COMPETITOR_") and source == "YOUTUBE_DATA_API_V3":
        if metric in COMPETITOR_PRIVATE_METRICS:
            evidence_class = "UNKNOWN"
        elif metric in COMPETITOR_PUBLIC_OFFICIAL_METRICS:
            evidence_class = "PUBLIC_OFFICIAL_METRIC"
        else:
            evidence_class = "UNKNOWN"
    else:
        evidence_class = "UNKNOWN"

    return MetricEvidenceClass(
        metric_name=metric,
        evidence_class=evidence_class,
        subject_scope=scope,
        source_system=source,
        provider=provider,
        retrieval_method=retrieval_method,
        compliance_status=compliance_status,
        observed_at=observed_at,
        source_ref=source_ref,
        confidence=confidence if evidence_class != "UNKNOWN" else "UNKNOWN",
        evidence_refs=(source_ref,),
    )


def build_channel_originality_policy() -> ChannelOriginalityPolicy:
    inauthentic = current_policy_snapshot("INAUTHENTIC_CONTENT")
    reused = current_policy_snapshot("REUSED_CONTENT")
    return ChannelOriginalityPolicy(
        required_value_signals=(
            "ORIGINAL_RESEARCH",
            "ORIGINAL_SYNTHESIS",
            "ORIGINAL_NARRATIVE",
            "ORIGINAL_COMMENTARY",
            "ORIGINAL_EDITING",
            "ORIGINAL_VISUAL_EXPLANATION",
            "BR_SPECIFIC_PERSPECTIVE",
        ),
        prohibited_patterns=(
            "GENERIC_MASS_PRODUCED_VIDEO",
            "TEMPLATE_EQUIVALENT_VIDEO",
            "THIN_AI_NARRATION_OVER_REUSED_FOOTAGE",
            "LOW_TRANSFORMATIVE_COMPILATION",
        ),
        policy_snapshot_refs=(policy_ref(inauthentic), policy_ref(reused)),
        evidence_refs=(inauthentic.source_url, reused.source_url),
    )


def evaluate_video_originality(
    *,
    video_id: str,
    copyright_status: str,
    original_research: bool,
    original_synthesis: bool,
    original_narrative: bool,
    original_commentary: bool,
    original_editing: bool,
    original_visual_explanation: bool,
    br_specific_perspective: bool,
    template_equivalent: bool,
    thin_ai_narration_over_reused_footage: bool,
    low_transformative_compilation: bool,
    evidence_refs: Sequence[str],
) -> VideoOriginalityReview:
    if not video_id:
        raise ValueError("video_id is required")
    policy = build_channel_originality_policy()
    signals = tuple(
        name
        for name, present in (
            ("ORIGINAL_RESEARCH", original_research),
            ("ORIGINAL_SYNTHESIS", original_synthesis),
            ("ORIGINAL_NARRATIVE", original_narrative),
            ("ORIGINAL_COMMENTARY", original_commentary),
            ("ORIGINAL_EDITING", original_editing),
            ("ORIGINAL_VISUAL_EXPLANATION", original_visual_explanation),
            ("BR_SPECIFIC_PERSPECTIVE", br_specific_perspective),
        )
        if present
    )
    risks = tuple(
        name
        for name, present in (
            ("TEMPLATE_EQUIVALENT_VIDEO", template_equivalent),
            ("THIN_AI_NARRATION_OVER_REUSED_FOOTAGE", thin_ai_narration_over_reused_footage),
            ("LOW_TRANSFORMATIVE_COMPILATION", low_transformative_compilation),
        )
        if present
    )
    if risks:
        transformative = "FAIL"
        decision = "REJECT"
    elif set(signals) == set(policy.required_value_signals):
        transformative = "PASS"
        decision = "PASS"
    else:
        transformative = "REVIEW_REQUIRED"
        decision = "REVIEW_REQUIRED"
    return VideoOriginalityReview(
        video_id=video_id,
        copyright_status=str(copyright_status or "UNKNOWN").upper(),
        ypp_transformative_value_status=transformative,
        original_value_signals=signals,
        risk_flags=risks,
        policy_snapshot_refs=policy.policy_snapshot_refs,
        decision=decision,
        evidence_refs=tuple(str(x) for x in evidence_refs if str(x)),
    )


def decide_synthetic_media_disclosure(
    *,
    realistic_media: bool,
    meaningfully_altered_or_generated: bool,
    uncertain: bool,
    rationale: str,
) -> SyntheticMediaDisclosureDecision:
    policy = current_policy_snapshot("AI_DISCLOSURE")
    if uncertain:
        decision = "UNCERTAIN_REVIEW_REQUIRED"
    elif realistic_media and meaningfully_altered_or_generated:
        decision = "REQUIRED"
    else:
        decision = "NOT_REQUIRED"
    return SyntheticMediaDisclosureDecision(
        decision=decision,
        realistic_media=bool(realistic_media),
        meaningfully_altered_or_generated=bool(meaningfully_altered_or_generated),
        rationale=str(rationale or ""),
        policy_snapshot_ref=policy_ref(policy),
        evidence_refs=(policy.source_url,),
    )


def operation_surface(operation: str) -> YouTubeOperationSurface:
    op = str(operation or "").strip()
    if op in {"youtube.data.read", "youtube.analytics.read", "youtube.reporting.read"}:
        return YouTubeOperationSurface(
            operation=op,
            surface="OFFICIAL_API",
            documented=True,
            source_url=(
                "https://developers.google.com/youtube/v3/docs/channels/list"
                if op == "youtube.data.read"
                else "https://developers.google.com/youtube/analytics/reference/reports/query"
                if op == "youtube.analytics.read"
                else "https://developers.google.com/youtube/reporting/v1/reference/rest"
            ),
            notes="official Google/YouTube API",
        )
    if op == "youtube.synthetic_media_disclosure":
        policy = current_policy_snapshot("AI_DISCLOSURE")
        return YouTubeOperationSurface(
            operation=op,
            surface="OFFICIAL_API",
            documented=True,
            source_url="https://developers.google.com/youtube/v3/docs/videos",
            policy_snapshot_ref=policy_ref(policy),
            notes="Data API status.containsSyntheticMedia",
        )
    if op == "youtube.native_ab_test":
        policy = current_policy_snapshot("A_B_ELIGIBILITY")
        return YouTubeOperationSurface(
            operation=op,
            surface="STUDIO_ONLY",
            documented=True,
            source_url=policy.source_url,
            policy_snapshot_ref=policy_ref(policy),
            notes="native title/thumbnail test is a YouTube Studio feature; private videos are ineligible",
        )
    if op == "youtube.midroll.manage":
        policy = current_policy_snapshot("MIDROLL")
        return YouTubeOperationSurface(
            operation=op,
            surface="STUDIO_ONLY",
            documented=True,
            source_url=policy.source_url,
            policy_snapshot_ref=policy_ref(policy),
            notes="manual mid-roll slot management is documented in YouTube Studio",
        )
    return YouTubeOperationSurface(
        operation=op,
        surface="UNAVAILABLE",
        documented=False,
        source_url="",
        notes="no documented supported surface registered",
    )


def youtube_integration_inventory() -> tuple[dict[str, Any], ...]:
    return (
        {
            "integration_id": "google-youtube-data-v3",
            "classification": "OFFICIAL_API_ADAPTER",
            "provider": "Google/YouTube",
            "retrieval_method": "OAuth2 + YouTube Data API v3",
            "terms_compliance_status": "OFFICIAL_API",
            "may_claim_owned_private_metrics": False,
        },
        {
            "integration_id": "google-youtube-analytics-v2",
            "classification": "ANALYTICS_PROVIDER",
            "provider": "Google/YouTube",
            "retrieval_method": "OAuth2 + YouTube Analytics API v2",
            "terms_compliance_status": "OFFICIAL_API",
            "may_claim_owned_private_metrics": True,
        },
        {
            "integration_id": "google-youtube-reporting-v1",
            "classification": "ANALYTICS_PROVIDER",
            "provider": "Google/YouTube",
            "retrieval_method": "OAuth2 + YouTube Reporting API v1",
            "terms_compliance_status": "OFFICIAL_API",
            "may_claim_owned_private_metrics": True,
        },
        {
            "integration_id": "youtube-private-upload-worker",
            "classification": "PUBLICATION_EXECUTOR",
            "provider": "BR-no-GTA",
            "retrieval_method": "trusted GitHub Actions runtime + official YouTube API",
            "terms_compliance_status": "OFFICIAL_API_EXECUTOR",
            "may_claim_owned_private_metrics": False,
        },
        {
            "integration_id": "agenttube-pinned",
            "classification": "THIRD_PARTY_RESEARCH_PROVIDER",
            "provider": "AgentTube/Lumen pinned adaptation",
            "retrieval_method": "local pinned capability adaptation",
            "terms_compliance_status": "PINNED_SOURCE_SECURITY_LICENSE_REVIEW",
            "may_claim_owned_private_metrics": False,
        },
        {
            "integration_id": "tubegent",
            "classification": "THIRD_PARTY_RESEARCH_PROVIDER",
            "provider": "TUBEGENT specialist adaptation",
            "retrieval_method": "Harness-subordinated semantic specialist",
            "terms_compliance_status": "NO_DIRECT_YOUTUBE_PRIVATE_DATA_AUTHORITY",
            "may_claim_owned_private_metrics": False,
        },
        {
            "integration_id": "tubealfred",
            "classification": "THIRD_PARTY_RESEARCH_PROVIDER",
            "provider": "TubeAlfred connector",
            "retrieval_method": "connected third-party provider",
            "terms_compliance_status": "TERMS_AND_SOURCE_PROVENANCE_REQUIRED_PER_RESULT",
            "may_claim_owned_private_metrics": False,
        },
    )


__all__ = [
    "METRIC_EVIDENCE_CLASSES",
    "classify_metric_evidence",
    "build_channel_originality_policy",
    "evaluate_video_originality",
    "decide_synthetic_media_disclosure",
    "operation_surface",
    "youtube_integration_inventory",
]
