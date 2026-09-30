from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from app.database.schema import initialize_schema
from app.database import youtube_intelligence_repository as repository
from app.services.google_oauth import _resolved_scopes
from app.services.youtube_credential_broker_service import (
    YouTubeCredentialBrokerClient,
    YouTubeCredentialBrokerError,
    YouTubeRemoteStateUnknown,
    scopes_for_operation,
)
from app.services.youtube_quota_service import consume_quota, quota_cost
from app.services.youtube_reporting_warehouse_service import (
    REACH_COMBINED_REPORT,
    normalize_reach_rows,
    persist_report_revision,
)
from app.services.youtube_opportunity_business_service import (
    build_editorial_opportunity,
    build_video_strategy_brief,
    calculate_video_business_outcome,
)
from app.services.youtube_retention_lifecycle_service import (
    advertiser_suitability_review,
    build_hook_contract,
    build_retention_blueprint,
    build_retention_event,
    learning_episode_eligibility,
    natural_ad_break_candidates,
)
from app.contracts.youtube_intelligence_contracts import (
    PackagingVariantSet,
    VideoPostmortem,
)
from app.services.youtube_intelligence_capability_bridge import (
    youtube_intelligence_capability_records,
)
from app.services.youtube_competitor_audience_service import (
    evaluate_competitor_corpus,
    cluster_comment_intelligence,
    build_editorial_gap_map,
)
from app.services.youtube_publication_spec_v1_service import (
    build_youtube_publication_spec,
    publication_spec_to_private_upload,
    validate_publication_spec_against_master,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.youtube_intelligence_revenue_plane_service import (
    build_acceptance_snapshot,
    build_plane_snapshot,
    validate_closed_loop_progression,
)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BR_TEST_DATABASE", str(tmp_path / "youtube-intel.db"))
    initialize_schema()


def test_explicit_oauth_scope_does_not_inherit_upload_scope():
    readonly="https://www.googleapis.com/auth/youtube.readonly"
    scopes=_resolved_scopes((readonly,))
    assert scopes==[readonly]
    assert "https://www.googleapis.com/auth/youtube.upload" not in scopes


def test_quota_profiles_match_current_separate_search_upload_buckets():
    assert quota_cost("youtube_data","search.list")==1
    assert quota_cost("youtube_data","videos.insert")==1
    assert quota_cost("youtube_data","videos.update")==50
    assert quota_cost("youtube_data","thumbnails.set")==50


def test_quota_cache_hit_consumes_zero_and_budget_is_durable():
    first=consume_quota(
        api="youtube_data",
        operation="search.list",
        request_identity={"q":"GTA VI"},
        cache_state="MISS",
        hard_limit=100,
    )
    second=consume_quota(
        api="youtube_data",
        operation="search.list",
        request_identity={"q":"GTA VI"},
        cache_state="HIT",
        hard_limit=100,
    )
    assert first.consumed==1
    assert second.consumed==1
    assert second.estimated_unit_cost==0
    assert second.remaining==99


def test_reporting_reach_requires_impressions_ctr_and_traffic_device_dimensions():
    rows=[{
        "date":"2026-09-29",
        "channel_id":"UC1",
        "video_id":"vid1",
        "traffic_source_type":"YT_SEARCH",
        "traffic_source_detail":"gta 6",
        "operating_system":"ANDROID",
        "device_type":"MOBILE",
        "video_thumbnail_impressions":"1000",
        "video_thumbnail_impressions_ctr":"0.08",
    }]
    normalized=normalize_reach_rows(rows,report_type=REACH_COMBINED_REPORT)
    assert normalized[0]["video_thumbnail_impressions"]==1000
    assert normalized[0]["video_thumbnail_impressions_ctr"]==0.08
    assert normalized[0]["traffic_source_type"]=="YT_SEARCH"


def test_reporting_revisions_are_append_only_and_backfill_preserved():
    rows=[{
        "date":"2026-09-29",
        "channel_id":"UC1",
        "video_id":"vid1",
        "traffic_source_type":"BROWSE",
        "traffic_source_detail":"",
        "operating_system":"ANDROID",
        "device_type":"MOBILE",
        "video_thumbnail_impressions":100,
        "video_thumbnail_impressions_ctr":0.05,
    }]
    one=persist_report_revision(
        report_id="r1",
        report_type=REACH_COMBINED_REPORT,
        period_start="2026-09-29",
        period_end="2026-09-29",
        revision=1,
        backfill_state="INITIAL",
        rows=rows,
        evidence_refs=("youtube-report:r1:v1",),
    )
    rows2=[{**rows[0],"video_thumbnail_impressions":120}]
    two=persist_report_revision(
        report_id="r1",
        report_type=REACH_COMBINED_REPORT,
        period_start="2026-09-29",
        period_end="2026-09-29",
        revision=2,
        backfill_state="BACKFILLED",
        rows=rows2,
        evidence_refs=("youtube-report:r1:v2",),
    )
    assert one.snapshot_id!=two.snapshot_id
    assert one.revision==1 and two.revision==2


def test_opportunity_never_equates_trend_with_opportunity_and_requires_20m_depth():
    with pytest.raises(ValueError,match="20"):
        build_editorial_opportunity(
            opportunity_id="opp-1",
            topic="Mapa",
            trigger="trending search",
            target_audience="BR GTA VI",
            viewer_problem="O que mudou?",
            demand_evidence=("yt:search:gta6",),
            competition_evidence=("yt:video:x",),
            content_gap="ângulo brasileiro",
            official_evidence_availability="OFFICIAL",
            expected_depth_minutes=10,
            catalog_relationship="MAP INTELLIGENCE",
            monetization_risks=(),
            components={
                "demand":0.9,
                "competition":0.5,
                "freshness":0.9,
                "br_audience_relevance":0.9,
                "available_evidence":0.9,
                "supported_20m_depth":0.2,
                "novelty":0.8,
                "monetization_suitability":0.8,
                "catalog_fit":0.8,
            },
            evidence_refs=("official:rockstar",),
        )


def test_video_strategy_requires_viewer_promise():
    opportunity=build_editorial_opportunity(
        opportunity_id="opp-2",
        topic="Every detail",
        trigger="official trailer",
        target_audience="BR GTA VI",
        viewer_problem="O que passou despercebido?",
        demand_evidence=("signal:demand",),
        competition_evidence=("signal:competition",),
        content_gap="evidence-first PT-BR",
        official_evidence_availability="OFFICIAL",
        expected_depth_minutes=24,
        catalog_relationship="EVERY DETAIL",
        monetization_risks=(),
        components={key:0.7 for key in (
            "demand","competition","freshness","br_audience_relevance",
            "available_evidence","supported_20m_depth","novelty",
            "monetization_suitability","catalog_fit"
        )},
        evidence_refs=("official:rockstar",),
    )
    with pytest.raises(ValueError,match="viewer promise"):
        build_video_strategy_brief(
            opportunity=opportunity,
            target_viewer="BR GTA VI",
            viewer_promise="",
            core_question="O que mudou?",
            primary_value="Análise de evidência",
            novelty="PT-BR",
            why_now="release",
            content_pillar="EVERY DETAIL",
            competitive_differentiation="evidence-first",
            expected_duration_minutes=22,
            search_intent="gta 6 detalhes",
            browse_intent="curiosidade",
            suggested_video_relationship="scene by scene",
            series="EVERY DETAIL",
            next_video_path="map intelligence",
            revenue_considerations=(),
        )


def test_hook_and_retention_deliver_value_inside_first_30_seconds():
    hook=build_hook_contract(
        title_promise="Tudo que mudou",
        thumbnail_promise="31 detalhes",
        first_spoken_promise="Hoje você vai ver 31 detalhes verificáveis",
        proof_of_value="primeiro detalhe oficial",
        stakes="o que isso muda",
        novelty="frame-by-frame",
        first_visual_payoff="frame oficial",
        first_information_payoff="detalhe #1",
        open_loop="o detalhe final muda a leitura",
        expected_30s_behavior="entrega 2 achados antes de 30s",
        evidence_refs=("official:frame1",),
    )
    blueprint=build_retention_blueprint(
        hook=hook,
        first_value_timestamp=6,
        open_loops=("detalhe final",),
        section_payoffs=({"section":"1","payoff":"achado"},),
        novelty_cadence_seconds=35,
        visual_changes=({"t":8,"kind":"evidence"},),
        evidence_reveals=({"t":8,"ref":"official:frame1"},),
        story_progression=("evidence","implication"),
        re_hooks=({"t":120,"promise":"próximo achado"},),
        cta_positions=(900,),
        ad_break_candidates=(),
        ending_payoff="resposta final",
        end_screen_transition="ponte para scene-by-scene",
        evidence_refs=("official:frame1",),
    )
    assert blueprint.first_value_timestamp==6


def test_ad_break_planner_rejects_mid_sentence_and_pre_payoff_slots():
    candidates=natural_ad_break_candidates(
        transitions=(
            {"timestamp_seconds":600,"transition_type":"SECTION_TRANSITION","reason":"fim seção"},
            {"timestamp_seconds":900,"transition_type":"AUDIO_PAUSE","mid_sentence":True},
            {"timestamp_seconds":1200,"transition_type":"COMPLETED_PAYOFF","before_immediate_payoff":True},
        ),
        video_duration_seconds=1400,
        evidence_refs=("edit:timeline",),
    )
    assert len(candidates)==1
    assert candidates[0].timestamp_seconds==600


def test_advertiser_review_preserves_truth_and_classifies_avoidable_risk():
    review=advertiser_suitability_review(
        video_id="v1",
        observations={
            "title":"LOW","thumbnail":"LOW",
            "first_7_seconds":"MODERATE","first_30_seconds":"MODERATE",
        },
        categories={"graphic_violence":"MODERATE","drug_content":"LOW"},
        evidence_refs=("qa:advertiser",),
    )
    assert review.editorial_truth_preserved is True
    assert review.expected_monetization_impact=="MODERATE_RISK"


def test_retention_event_cause_remains_hypothesis():
    event=build_retention_event(
        video_id="v1",
        event_type="DIP",
        timestamp_seconds=432,
        script_section="mechanics",
        visual_section="broll-12",
        audio_section="voice-8",
        topic="wanted system",
        editing_pattern="static visual",
        hypothesized_cause="visual novelty dropped",
        evidence_refs=("analytics:retention:v1",),
    )
    assert event.cause_status=="HYPOTHESIS"


def test_skill_candidate_requires_multiple_episodes_heldout_and_review():
    postmortem=VideoPostmortem(
        video_id="v1",
        what_worked=("evidence reveals",),
        what_failed=("slow middle",),
        repeat_candidates=("evidence reveal",),
        retire_candidates=("generic filler",),
        evidence_refs=("postmortem:v1",),
    )
    one=learning_episode_eligibility(
        postmortem=postmortem,
        repeated_episode_count=1,
        held_out_evaluation_passed=True,
        independent_review_passed=True,
    )
    three=learning_episode_eligibility(
        postmortem=postmortem,
        repeated_episode_count=3,
        held_out_evaluation_passed=True,
        independent_review_passed=True,
    )
    assert one["skill_candidate_eligible"] is False
    assert three["skill_candidate_eligible"] is True
    assert three["auto_promote"] is False


def test_business_outcome_keeps_unknown_terms_unknown():
    result=calculate_video_business_outcome(
        video_id="v1",
        youtube_reported_revenue=100.0,
        external_confirmed_revenue=None,
        production_cost=20.0,
        promotion_cost=0.0,
        catalog_spillover_value=None,
        audience_growth_value=None,
        evidence_refs=("revenue:youtube",),
    )
    assert result.net_content_value is None
    assert "external_confirmed_revenue" in result.unknown_terms


def test_revenue_ledger_never_mixes_source_labels():
    row,_=repository.append_revenue_entry(
        entry_id="rev-1",
        video_id="v1",
        publication_id=1,
        revenue_class="ADS",
        source_label="YOUTUBE_REPORTED",
        amount=12.5,
        currency="USD",
        amount_status="ESTIMATED",
        period_start="2026-09-01",
        period_end="2026-09-30",
        evidence_refs=("youtube:analytics",),
    )
    assert row["source_label"]=="YOUTUBE_REPORTED"


def test_capability_registry_has_distinct_least_privilege_youtube_capabilities_and_roles():
    required={
        "youtube.data.read",
        "youtube.video.upload",
        "youtube.video.metadata.update",
        "youtube.thumbnail.set",
        "youtube.playlist.manage",
        "youtube.comment.read",
        "youtube.comment.reply",
        "youtube.reporting.read",
        "youtube.market-intelligence",
        "youtube.retention-analyst",
        "youtube.revenue-analyst",
        "youtube.postmortem-reviewer",
    }
    present={r.capability_id for r in GLOBAL_CAPABILITY_REGISTRY.all()}
    assert required.issubset(present)
    assert GLOBAL_CAPABILITY_REGISTRY.get("youtube.data.read").side_effect_class=="READ_ONLY"
    assert GLOBAL_CAPABILITY_REGISTRY.get("youtube.comment.reply").side_effect_class=="EXTERNAL_MUTATION"


def test_credential_broker_scope_profiles_are_operation_local():
    assert scopes_for_operation("DATA_READ")==(
        "https://www.googleapis.com/auth/youtube.readonly",
    )
    assert scopes_for_operation("ANALYTICS_MONETARY_READ")==(
        "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
    )
    assert "youtube.upload" not in scopes_for_operation("COMMENT_READ")[0]


def test_credential_broker_rejects_secret_material():
    def transport(endpoint,payload,headers):
        return {
            "credential_handle":"opaque",
            "expires_at":"2030-01-01T00:00:00+00:00",
            "broker_identity":"google-oauth-broker",
            "scopes":payload["required_scopes"],
            "access_token":"leak",
        }
    broker=YouTubeCredentialBrokerClient(
        base_url="https://broker.invalid",transport=transport
    )
    with pytest.raises(YouTubeCredentialBrokerError,match="secret"):
        broker.request_handle(
            operation="DATA_READ",
            authorization_ref="auth-1",
            task_id="task-1",
            resource_binding={"channel_id":"mine"},
        )


def test_competitor_corpus_requires_20_channels_50_videos_both_markets_and_samples():
    channels=[
        {"channel_id":f"c{i}","market":"BR" if i<10 else "GLOBAL"}
        for i in range(20)
    ]
    videos=[
        {
            "video_id":f"v{i}",
            "channel_id":f"c{i%20}",
            "transcript_ref":f"transcript:v{i}" if i<10 else None,
            "comments_ref":f"comments:v{i}" if i<10 else None,
        }
        for i in range(50)
    ]
    result=evaluate_competitor_corpus(channels=channels,videos=videos)
    assert result["status"]=="PASS"
    assert result["channel_count"]==20
    assert result["video_count"]==50
    assert result["no_unauthorized_scraping"] is True

    incomplete=evaluate_competitor_corpus(
        channels=channels[:5],
        videos=videos[:5],
    )
    assert incomplete["status"]=="INCOMPLETE"


def test_comment_intelligence_is_demand_signal_not_gta_factual_evidence():
    result=cluster_comment_intelligence([
        {"comment_id":"1","text":"Vocês podem explicar o mapa?"},
        {"comment_id":"2","text":"O meio ficou lento e repetitivo"},
        {"comment_id":"3","text":"Excelente nível de detalhe"},
    ])
    assert result["comments_are_factual_gta_evidence"] is False
    assert result["question_cluster"]["question_count"]==1
    assert result["complaint_cluster"]["complaint_count"]==1
    assert result["praise_cluster"]["praise_count"]==1


def test_editorial_gap_map_requires_evidence():
    with pytest.raises(ValueError,match="evidence"):
        build_editorial_gap_map(
            topic="Leonida",
            market="BR",
            competitor_coverage=("generic map news",),
            missing_angles=("official geography evidence",),
            br_specific_gaps=("PT-BR investigative framing",),
            evidence_refs=(),
        )


def test_publication_spec_is_private_first_and_bound_to_exact_master():
    sha="a"*64
    spec=build_youtube_publication_spec(
        video_id="video-1",
        master_artifact_sha=sha,
        title="31 detalhes oficiais de GTA VI",
        description="Análise evidence-first",
        thumbnail_ref="artifact:thumbnail:1",
        language="pt-BR",
        category="Gaming",
        playlist="EVERY DETAIL",
        series="EVERY DETAIL",
        chapters=({"time":"00:00","title":"Hook"},),
        privacy="PRIVATE",
        monetization_intent="ADS_ELIGIBLE_IF_POLICY_PASS",
        contains_synthetic_media=False,
        related_videos=("video-prev",),
        end_screen_plan={"target":"video-prev"},
        cards_plan=(),
        comment_strategy={"mode":"human_authorized_replies"},
        evidence_refs=("master:qa:pass",),
    )
    intent=publication_spec_to_private_upload(spec)
    assert intent["privacy"]=="PRIVATE"
    assert intent["human_review_required"] is True
    assert intent["public_transition_authorized"] is False
    validation=validate_publication_spec_against_master(
        spec,
        observed_master_sha=sha,
        master_qa_status="PASS",
        duration_seconds=20*60,
    )
    assert validation["status"]=="PASS"


def test_non_private_publication_spec_requires_explicit_human_approval():
    kwargs=dict(
        video_id="video-2",
        master_artifact_sha="b"*64,
        title="GTA VI",
        description="",
        thumbnail_ref="artifact:thumbnail:2",
        language="pt-BR",
        category="Gaming",
        playlist=None,
        series=None,
        chapters=(),
        privacy="PUBLIC",
        evidence_refs=("master:qa:pass",),
    )
    with pytest.raises(PermissionError,match="human approval"):
        build_youtube_publication_spec(**kwargs)
    spec=build_youtube_publication_spec(
        **kwargs,
        human_approval_ref="owner-approval:action-123",
    )
    assert spec.privacy=="PUBLIC"


def test_closed_loop_requires_evidence_for_every_stage_in_order():
    partial={
        "MARKET":("market:1",),
        "AUDIENCE_DEMAND":("demand:1",),
        "OPPORTUNITY":("opp:1",),
    }
    validation=validate_closed_loop_progression(
        partial,
        through_stage="CONTENT_STRATEGY",
    )
    assert validation["status"]=="INCOMPLETE"
    assert validation["missing_evidence_stages"]==["CONTENT_STRATEGY"]

    complete={**partial,"CONTENT_STRATEGY":("strategy:1",)}
    plane=build_plane_snapshot(
        video_or_opportunity_id="opp-1",
        stage_evidence=complete,
        current_stage="CONTENT_STRATEGY",
    )
    assert plane.authority=="DEEPSEEK_HARNESS"
    assert plane.second_control_plane is False


def test_acceptance_snapshot_never_promotes_external_configuration_to_pass():
    snapshot=build_acceptance_snapshot(
        internal_gates={
            "OAUTH_LEAST_PRIVILEGE":True,
            "API_QUOTA_GOVERNANCE":True,
        },
        external_gates={
            "YOUTUBE_DATA_API":"EXTERNAL_CONFIGURATION_REQUIRED",
            "COMPETITOR_CORPUS":"NOT_YET_PROVEN",
        },
    )
    assert snapshot["all_internal_pass"] is True
    assert snapshot["live_external_complete"] is False
    assert snapshot["no_external_truth_fabrication"] is True
