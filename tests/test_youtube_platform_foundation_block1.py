from __future__ import annotations

from datetime import date

import pytest

from app.contracts.youtube_intelligence_contracts import (
    ChannelOriginalityPolicy,
    MetricEvidenceClass,
    SyntheticMediaDisclosureDecision,
    VideoOriginalityReview,
    YouTubeOperationSurface,
    YouTubePolicySnapshot,
)
from app.services.youtube_credential_broker_service import scopes_for_operation
from app.services.youtube_platform_foundation_service import (
    build_channel_originality_policy,
    classify_metric_evidence,
    decide_synthetic_media_disclosure,
    evaluate_video_originality,
    operation_surface,
    youtube_integration_inventory,
)
from app.services.youtube_policy_registry_service import (
    current_policy_snapshot,
    load_policy_snapshots,
)
from app.services.youtube_quota_service import quota_policy
from app.services.youtube_analytics_service import (
    normalize_retention_series,
    retention_query_parameters,
)


def test_policy_registry_has_all_block1_families_and_verified_digests():
    snapshots = load_policy_snapshots()
    assert snapshots
    assert all(isinstance(item, YouTubePolicySnapshot) for item in snapshots)
    families = {item.policy_family for item in snapshots}
    assert {
        "API_QUOTA",
        "YPP_ELIGIBILITY",
        "ADVERTISER_FRIENDLY",
        "AI_DISCLOSURE",
        "INAUTHENTIC_CONTENT",
        "REUSED_CONTENT",
        "MIDROLL",
        "A_B_ELIGIBILITY",
        "SHOPPING",
    }.issubset(families)
    assert all(len(item.content_digest) == 64 for item in snapshots)


def test_policy_registry_resolves_current_and_scheduled_ypp_without_magic_numbers():
    current = current_policy_snapshot("YPP_ELIGIBILITY", on_date=date(2026, 9, 30))
    future = current_policy_snapshot("YPP_ELIGIBILITY", on_date=date(2027, 2, 1))
    assert current.policy_id != future.policy_id
    assert future.effective_from == "2027-02-01"
    assert future.structured_values["ads_premium_entry"]["qualified_watch_hours_365d"] == 8000
    assert future.structured_values["ads_premium_entry"]["qualified_shorts_views_90d"] == 20_000_000


def test_quota_policy_is_loaded_from_policy_snapshot_and_tracks_bucket_and_pagination():
    search = quota_policy("youtube_data", "search.list", on_date=date(2026, 9, 30))
    videos = quota_policy("youtube_data", "videos.list", on_date=date(2026, 9, 30))
    assert search["quota_bucket"] == "SEARCH_QUERIES"
    assert search["hard_limit"] == 100
    assert search["operation_cost"] == 1
    assert search["pagination_cost"] == 1
    assert videos["quota_bucket"] == "STANDARD_PROJECT_QUOTA"
    assert videos["hard_limit"] == 10_000
    assert videos["operation_cost"] == 1
    assert len(search["policy_digest"]) == 64
    snapshot = current_policy_snapshot("API_QUOTA", on_date=date(2026, 9, 30))
    youtube_data = snapshot.structured_values["api_families"]["youtube_data"]
    assert youtube_data["effective_project_limit_observation_source"] == "GOOGLE_CLOUD_CONSOLE"
    assert youtube_data["public_documentation_exposes_documented_default_limits"] is True
    assert youtube_data["project_limit_may_be_overridden"] is True
    assert youtube_data["reset_time"] == "MIDNIGHT_PT"


def test_analytics_scope_profiles_are_least_privilege_and_follow_current_official_requirement():
    assert scopes_for_operation("ANALYTICS_READ") == (
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    )
    assert scopes_for_operation("ANALYTICS_MONETARY_READ") == (
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
    )
    assert "youtube.upload" not in " ".join(scopes_for_operation("ANALYTICS_READ"))


def test_metric_provenance_separates_owned_private_public_official_and_unknown_competitor_private_metrics():
    owned_retention = classify_metric_evidence(
        metric_name="audienceWatchRatio",
        subject_scope="OWNED_VIDEO",
        source_system="YOUTUBE_ANALYTICS_API",
        observed_at="2026-09-30T00:00:00Z",
        source_ref="analytics:v1",
    )
    public_views = classify_metric_evidence(
        metric_name="viewCount",
        subject_scope="COMPETITOR_VIDEO",
        source_system="YOUTUBE_DATA_API_V3",
        observed_at="2026-09-30T00:00:00Z",
        source_ref="youtube:video:v2",
    )
    impossible = classify_metric_evidence(
        metric_name="relativeRetentionPerformance",
        subject_scope="COMPETITOR_VIDEO",
        source_system="YOUTUBE_DATA_API_V3",
        observed_at="2026-09-30T00:00:00Z",
        source_ref="youtube:video:v2",
    )
    assert isinstance(owned_retention, MetricEvidenceClass)
    assert owned_retention.evidence_class == "OWNED_PRIVATE_METRIC"
    assert public_views.evidence_class == "PUBLIC_OFFICIAL_METRIC"
    assert impossible.evidence_class == "UNKNOWN"


def test_third_party_metric_requires_provider_retrieval_method_and_compliance_status():
    with pytest.raises(ValueError, match="provider"):
        classify_metric_evidence(
            metric_name="transcript",
            subject_scope="COMPETITOR_VIDEO",
            source_system="THIRD_PARTY",
            observed_at="2026-09-30T00:00:00Z",
            source_ref="thirdparty:v1",
        )
    record = classify_metric_evidence(
        metric_name="transcript",
        subject_scope="COMPETITOR_VIDEO",
        source_system="THIRD_PARTY",
        provider="TubeAlfred",
        retrieval_method="CONNECTED_PROVIDER",
        compliance_status="TERMS_REVIEW_REQUIRED",
        observed_at="2026-09-30T00:00:00Z",
        source_ref="thirdparty:v1",
    )
    assert record.evidence_class == "THIRD_PARTY_PROVIDER"


def test_operation_surface_marks_native_ab_and_midroll_as_studio_only_but_disclosure_as_official_api():
    ab = operation_surface("youtube.native_ab_test")
    midroll = operation_surface("youtube.midroll.manage")
    disclosure = operation_surface("youtube.synthetic_media_disclosure")
    assert isinstance(ab, YouTubeOperationSurface)
    assert ab.surface == "STUDIO_ONLY"
    assert midroll.surface == "STUDIO_ONLY"
    assert disclosure.surface == "OFFICIAL_API"
    assert disclosure.documented is True


def test_synthetic_disclosure_decision_is_bound_to_current_policy():
    required = decide_synthetic_media_disclosure(
        realistic_media=True,
        meaningfully_altered_or_generated=True,
        uncertain=False,
        rationale="realistic generated reconstruction",
    )
    not_required = decide_synthetic_media_disclosure(
        realistic_media=False,
        meaningfully_altered_or_generated=True,
        uncertain=False,
        rationale="clearly stylized non-realistic animation",
    )
    uncertain = decide_synthetic_media_disclosure(
        realistic_media=True,
        meaningfully_altered_or_generated=False,
        uncertain=True,
        rationale="human review needed",
    )
    assert isinstance(required, SyntheticMediaDisclosureDecision)
    assert required.decision == "REQUIRED"
    assert not_required.decision == "NOT_REQUIRED"
    assert uncertain.decision == "UNCERTAIN_REVIEW_REQUIRED"
    assert required.policy_snapshot_ref.startswith("youtube-policy:")


def test_originality_review_keeps_copyright_and_ypp_transformative_value_separate():
    policy = build_channel_originality_policy()
    assert isinstance(policy, ChannelOriginalityPolicy)
    review = evaluate_video_originality(
        video_id="v1",
        copyright_status="PASS",
        original_research=True,
        original_synthesis=True,
        original_narrative=True,
        original_commentary=True,
        original_editing=True,
        original_visual_explanation=True,
        br_specific_perspective=True,
        template_equivalent=False,
        thin_ai_narration_over_reused_footage=False,
        low_transformative_compilation=False,
        evidence_refs=("editorial:v1", "edit:v1"),
    )
    assert isinstance(review, VideoOriginalityReview)
    assert review.copyright_status == "PASS"
    assert review.ypp_transformative_value_status == "PASS"
    assert review.copyright_status != review.ypp_transformative_value_status or review.schema == "VideoOriginalityReview/v1"


def test_retention_query_uses_official_curve_dimension_and_metrics_and_normalizes_content_addressed_series():
    params = retention_query_parameters(
        video_id="abc123",
        start_date="2026-09-01",
        end_date="2026-09-30",
    )
    assert params["dimensions"] == "elapsedVideoTimeRatio"
    assert params["metrics"] == "audienceWatchRatio,relativeRetentionPerformance"
    assert params["filters"] == "video==abc123"

    snapshot = normalize_retention_series(
        video_id="abc123",
        start_date="2026-09-01",
        end_date="2026-09-30",
        response={
            "columnHeaders": [
                {"name": "elapsedVideoTimeRatio"},
                {"name": "audienceWatchRatio"},
                {"name": "relativeRetentionPerformance"},
            ],
            "rows": [[0.0, 1.0, 0.2], [0.5, 0.61, -0.1], [1.0, 0.32, 0.05]],
        },
        evidence_refs=("youtube-analytics:retention:abc123",),
    )
    assert snapshot.schema == "YouTubeRetentionSeries/v1"
    assert len(snapshot.content_digest) == 64
    assert snapshot.points[1]["elapsedVideoTimeRatio"] == 0.5
    assert snapshot.metric_provenance["audienceWatchRatio"] == "OWNED_PRIVATE_METRIC"


def test_youtube_integration_inventory_names_each_stack_and_prevents_official_metric_confusion():
    inventory = {item["integration_id"]: item for item in youtube_integration_inventory()}
    assert inventory["google-youtube-data-v3"]["classification"] == "OFFICIAL_API_ADAPTER"
    assert inventory["google-youtube-analytics-v2"]["classification"] == "ANALYTICS_PROVIDER"
    assert inventory["google-youtube-reporting-v1"]["classification"] == "ANALYTICS_PROVIDER"
    assert inventory["youtube-private-upload-worker"]["classification"] == "PUBLICATION_EXECUTOR"
    assert inventory["agenttube-pinned"]["classification"] == "THIRD_PARTY_RESEARCH_PROVIDER"
    assert inventory["tubegent"]["classification"] == "THIRD_PARTY_RESEARCH_PROVIDER"
    assert inventory["tubealfred"]["classification"] == "THIRD_PARTY_RESEARCH_PROVIDER"
    assert inventory["tubealfred"]["may_claim_owned_private_metrics"] is False


def test_publication_spec_binds_synthetic_disclosure_and_public_originality_review():
    from app.services.youtube_publication_spec_v1_service import build_youtube_publication_spec

    required = decide_synthetic_media_disclosure(
        realistic_media=True,
        meaningfully_altered_or_generated=True,
        uncertain=False,
        rationale="realistic generated reconstruction",
    )
    base = dict(
        video_id="video-synthetic",
        master_artifact_sha="c" * 64,
        title="GTA VI análise",
        description="",
        thumbnail_ref="artifact:thumb",
        language="pt-BR",
        category="Gaming",
        playlist=None,
        series=None,
        chapters=(),
        evidence_refs=("master:qa",),
    )
    with pytest.raises(PermissionError, match="synthetic media disclosure"):
        build_youtube_publication_spec(
            **base,
            contains_synthetic_media=True,
        )

    private = build_youtube_publication_spec(
        **base,
        contains_synthetic_media=True,
        synthetic_media_disclosure_decision=required,
    )
    assert private.synthetic_media_disclosure["decision"] == "REQUIRED"
    assert private.contains_synthetic_media is True

    with pytest.raises(PermissionError, match="originality"):
        build_youtube_publication_spec(
            **base,
            privacy="PUBLIC",
            human_approval_ref="owner:approval",
            contains_synthetic_media=True,
            synthetic_media_disclosure_decision=required,
        )

    public = build_youtube_publication_spec(
        **base,
        privacy="PUBLIC",
        human_approval_ref="owner:approval",
        contains_synthetic_media=True,
        synthetic_media_disclosure_decision=required,
        originality_review_ref="originality:video-synthetic",
        ypp_transformative_value_status="PASS",
    )
    assert public.originality_review_ref == "originality:video-synthetic"
    assert public.ypp_transformative_value_status == "PASS"
