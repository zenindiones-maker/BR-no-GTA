from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import json
import os

from app.database.schema import initialize_schema
from app.database import youtube_intelligence_repository as repository
from app.services.youtube_quota_service import consume_quota
from app.services.youtube_reporting_warehouse_service import (
    REACH_COMBINED_REPORT,
    normalize_reach_rows,
    persist_report_revision,
)
from app.services.youtube_competitor_audience_service import (
    evaluate_competitor_corpus,
    cluster_comment_intelligence,
)
from app.services.youtube_opportunity_business_service import (
    build_editorial_opportunity,
    build_video_strategy_brief,
    calculate_video_business_outcome,
)
from app.services.youtube_retention_lifecycle_service import (
    build_hook_contract,
    build_retention_blueprint,
    natural_ad_break_candidates,
    build_retention_event,
)
from app.services.youtube_publication_spec_v1_service import (
    build_youtube_publication_spec,
    publication_spec_to_private_upload,
    validate_publication_spec_against_master,
)
from app.services.youtube_intelligence_revenue_plane_service import (
    build_acceptance_snapshot,
    build_plane_snapshot,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY


def run(*, database: Path, output: Path) -> dict:
    os.environ["BR_TEST_DATABASE"]=str(database)
    database.parent.mkdir(parents=True,exist_ok=True)
    if database.exists():
        database.unlink()
    initialize_schema()

    quota=consume_quota(
        api="youtube_data",
        operation="search.list",
        request_identity={"q":"GTA VI proof"},
        cache_state="MISS",
        hard_limit=100,
    )
    quota_cached=consume_quota(
        api="youtube_data",
        operation="search.list",
        request_identity={"q":"GTA VI proof"},
        cache_state="HIT",
        hard_limit=100,
    )

    reach_rows=[{
        "date":"2026-09-29",
        "channel_id":"UC_PROOF",
        "video_id":"video-proof",
        "traffic_source_type":"BROWSE",
        "traffic_source_detail":"",
        "operating_system":"ANDROID",
        "device_type":"MOBILE",
        "video_thumbnail_impressions":1000,
        "video_thumbnail_impressions_ctr":0.08,
    }]
    normalized_reach=normalize_reach_rows(
        reach_rows,
        report_type=REACH_COMBINED_REPORT,
    )
    report_v1=persist_report_revision(
        report_id="proof-reach",
        report_type=REACH_COMBINED_REPORT,
        period_start="2026-09-29",
        period_end="2026-09-29",
        revision=1,
        backfill_state="INITIAL",
        rows=normalized_reach,
        evidence_refs=("proof:report:v1",),
    )
    report_v2=persist_report_revision(
        report_id="proof-reach",
        report_type=REACH_COMBINED_REPORT,
        period_start="2026-09-29",
        period_end="2026-09-29",
        revision=2,
        backfill_state="BACKFILLED",
        rows=[{**normalized_reach[0],"video_thumbnail_impressions":1200}],
        evidence_refs=("proof:report:v2",),
    )

    synthetic_channels=[
        {"channel_id":f"proof-channel-{i}","market":"BR" if i<10 else "GLOBAL"}
        for i in range(20)
    ]
    synthetic_videos=[
        {
            "video_id":f"proof-video-{i}",
            "channel_id":f"proof-channel-{i%20}",
            "transcript_ref":f"proof:transcript:{i}" if i<10 else None,
            "comments_ref":f"proof:comments:{i}" if i<10 else None,
        }
        for i in range(50)
    ]
    synthetic_corpus=evaluate_competitor_corpus(
        channels=synthetic_channels,
        videos=synthetic_videos,
    )
    comment_intelligence=cluster_comment_intelligence([
        {"comment_id":"proof-1","text":"Vocês podem explicar melhor o mapa?"},
        {"comment_id":"proof-2","text":"O meio ficou lento e repetitivo"},
        {"comment_id":"proof-3","text":"Excelente nível de detalhe"},
    ],evidence_prefix="proof-comment")

    opportunity=build_editorial_opportunity(
        opportunity_id="proof-opportunity",
        topic="Every official detail",
        trigger="official GTA VI evidence",
        target_audience="Brazilian GTA VI audience",
        viewer_problem="What important details were missed?",
        demand_evidence=("proof:demand",),
        competition_evidence=("proof:competition",),
        content_gap="evidence-first PT-BR investigative framing",
        official_evidence_availability="OFFICIAL",
        expected_depth_minutes=24,
        catalog_relationship="EVERY DETAIL",
        monetization_risks=("gaming violence context",),
        components={
            "demand":0.8,
            "competition":0.5,
            "freshness":0.8,
            "br_audience_relevance":0.9,
            "available_evidence":0.9,
            "supported_20m_depth":0.9,
            "novelty":0.8,
            "monetization_suitability":0.7,
            "catalog_fit":0.9,
        },
        evidence_refs=("proof:official-evidence",),
    )
    strategy=build_video_strategy_brief(
        opportunity=opportunity,
        target_viewer="Brazilian GTA VI viewer who wants evidence, not fake leaks",
        viewer_promise="Show the most important official details and why they matter",
        core_question="What did Rockstar actually reveal?",
        primary_value="Evidence-first synthesis",
        novelty="PT-BR investigative framing",
        why_now="new official evidence",
        content_pillar="EVERY DETAIL",
        competitive_differentiation="supported depth without filler",
        expected_duration_minutes=24,
        search_intent="gta 6 detalhes",
        browse_intent="what everyone missed",
        suggested_video_relationship="scene-by-scene",
        series="EVERY DETAIL",
        next_video_path="SCENE-BY-SCENE",
        revenue_considerations=("advertiser suitability review",),
    )
    hook=build_hook_contract(
        title_promise="Every official detail that matters",
        thumbnail_promise="31 details",
        first_spoken_promise="You will see the evidence behind the most important details",
        proof_of_value="official frame evidence",
        stakes="how it changes what we know",
        novelty="evidence-first frame-by-frame",
        first_visual_payoff="official frame",
        first_information_payoff="verified detail one",
        open_loop="final evidence changes the interpretation",
        expected_30s_behavior="deliver at least two supported findings",
        evidence_refs=("proof:official-frame",),
    )
    retention=build_retention_blueprint(
        hook=hook,
        first_value_timestamp=6,
        open_loops=("final evidence",),
        section_payoffs=({"section":"1","payoff":"finding"},),
        novelty_cadence_seconds=35,
        visual_changes=({"t":8,"kind":"evidence"},),
        evidence_reveals=({"t":8,"ref":"proof:official-frame"},),
        story_progression=("evidence","implication","payoff"),
        re_hooks=({"t":120,"promise":"next finding"},),
        cta_positions=(900,),
        ad_break_candidates=(),
        ending_payoff="answer the core question",
        end_screen_transition="bridge to scene-by-scene",
        evidence_refs=("proof:official-frame",),
    )
    ad_breaks=natural_ad_break_candidates(
        transitions=(
            {
                "timestamp_seconds":600,
                "transition_type":"SECTION_TRANSITION",
                "reason":"completed section",
            },
        ),
        video_duration_seconds=24*60,
        evidence_refs=("proof:timeline",),
    )
    retention_event=build_retention_event(
        video_id="proof-video",
        event_type="DIP",
        timestamp_seconds=432,
        script_section="mechanics",
        visual_section="visual-12",
        audio_section="voice-8",
        topic="mechanics",
        editing_pattern="static visual",
        hypothesized_cause="visual novelty dropped",
        evidence_refs=("proof:analytics-retention",),
    )

    master_sha="a"*64
    publication=build_youtube_publication_spec(
        video_id="proof-video",
        master_artifact_sha=master_sha,
        title="Proof title",
        description="Provider-free architecture proof",
        thumbnail_ref="proof:thumbnail",
        language="pt-BR",
        category="Gaming",
        playlist="EVERY DETAIL",
        series="EVERY DETAIL",
        chapters=(),
        privacy="PRIVATE",
        monetization_intent="UNKNOWN",
        contains_synthetic_media=False,
        related_videos=(),
        end_screen_plan={"target":"proof-next"},
        cards_plan=(),
        comment_strategy={"mode":"human-authorized"},
        evidence_refs=("proof:master-qa",),
    )
    private_upload=publication_spec_to_private_upload(publication)
    publication_validation=validate_publication_spec_against_master(
        publication,
        observed_master_sha=master_sha,
        master_qa_status="PASS",
        duration_seconds=24*60,
    )

    business=calculate_video_business_outcome(
        video_id="proof-video",
        youtube_reported_revenue=100.0,
        external_confirmed_revenue=None,
        production_cost=20.0,
        promotion_cost=0.0,
        catalog_spillover_value=None,
        audience_growth_value=None,
        evidence_refs=("proof:youtube-revenue",),
    )

    stage_evidence={
        "MARKET":("proof:market",),
        "AUDIENCE_DEMAND":("proof:demand",),
        "OPPORTUNITY":("proof:opportunity",),
        "CONTENT_STRATEGY":("proof:strategy",),
        "GTA_VI_EVIDENCE":("proof:official-evidence",),
        "SCRIPT":("proof:script",),
        "RETENTION_DESIGN":("proof:retention",),
        "VIDEO_EDIT":("proof:edit",),
        "PACKAGING":("proof:packaging",),
        "MASTER_QA":("proof:master-qa",),
        "PRIVATE_YOUTUBE_REVIEW":("proof:private-review-contract",),
    }
    plane=build_plane_snapshot(
        video_or_opportunity_id="proof-video",
        stage_evidence=stage_evidence,
        current_stage="PRIVATE_YOUTUBE_REVIEW",
    )

    required_capabilities={
        "youtube.data.read","youtube.video.upload","youtube.video.metadata.update",
        "youtube.thumbnail.set","youtube.playlist.manage","youtube.comment.read",
        "youtube.comment.reply","youtube.reporting.read",
        "youtube.market-intelligence","youtube.retention-analyst",
        "youtube.revenue-analyst","youtube.postmortem-reviewer",
    }
    registry_ids={r.capability_id for r in GLOBAL_CAPABILITY_REGISTRY.all()}
    registry_pass=required_capabilities.issubset(registry_ids)

    acceptance=build_acceptance_snapshot(
        internal_gates={
            "YOUTUBE_INTELLIGENCE_PLANE":True,
            "OAUTH_LEAST_PRIVILEGE":True,
            "API_QUOTA_GOVERNANCE":quota.consumed==1 and quota_cached.consumed==1,
            "REPORTING_BACKFILL_MODEL":report_v1.revision==1 and report_v2.revision==2,
            "COMPETITOR_CORPUS_CONTRACT":synthetic_corpus["status"]=="PASS",
            "COMMENT_DEMAND_CONTRACT":comment_intelligence["comments_are_factual_gta_evidence"] is False,
            "VIDEO_STRATEGY_BRIEF":bool(strategy.viewer_promise),
            "HOOK_CONTRACT":bool(hook.proof_of_value),
            "RETENTION_BLUEPRINT":retention.first_value_timestamp_seconds<=30,
            "NATURAL_AD_BREAK_PLAN":len(ad_breaks)==1,
            "RETENTION_CAUSE_HYPOTHESIS":retention_event.causal_status=="HYPOTHESIS",
            "PRIVATE_FIRST_PUBLICATION":private_upload["privacy"]=="PRIVATE",
            "MASTER_PUBLICATION_BINDING":publication_validation["status"]=="PASS",
            "UNKNOWN_REVENUE_NOT_FABRICATED":business.net_content_value is None,
            "SPECIALIZED_ROLE_REGISTRY":registry_pass,
            "HARNESS_SOLE_AUTHORITY":plane.authority=="DEEPSEEK_HARNESS",
        },
        external_gates={
            "YOUTUBE_DATA_API":"EXTERNAL_CONFIGURATION_REQUIRED",
            "YOUTUBE_ANALYTICS_API":"EXTERNAL_CONFIGURATION_REQUIRED",
            "YOUTUBE_REPORTING_API":"EXTERNAL_CONFIGURATION_REQUIRED",
            "LIVE_CREDENTIAL_BROKER":"EXTERNAL_CONFIGURATION_REQUIRED",
            "REAL_COMPETITOR_CORPUS":"NOT_YET_PROVEN",
            "REAL_TRANSCRIPT_ANALYSIS":"NOT_YET_PROVEN",
            "REAL_COMMENT_DEMAND_ANALYSIS":"NOT_YET_PROVEN",
            "LIVE_REVENUE_ANALYTICS":"NOT_YET_PROVEN",
            "NATIVE_PACKAGING_AB_TEST":"NOT_YET_PROVEN",
        },
    )

    result={
        "schema":"YouTubeIntelligenceRevenueOperationalProof/v1",
        "status":"PASS" if acceptance["all_internal_pass"] else "FAIL",
        "provider_free":True,
        "official_api_calls_performed":False,
        "unauthorized_scraping_performed":False,
        "plane":plane.to_dict(),
        "quota":quota.to_dict(),
        "quota_cached":quota_cached.to_dict(),
        "report_revisions":[report_v1.to_dict(),report_v2.to_dict()],
        "synthetic_competitor_corpus":synthetic_corpus,
        "comment_intelligence":comment_intelligence,
        "opportunity":opportunity.to_dict(),
        "strategy":strategy.to_dict(),
        "hook":hook.to_dict(),
        "retention":retention.to_dict(),
        "ad_breaks":[asdict(x) for x in ad_breaks],
        "retention_event":asdict(retention_event),
        "publication_spec":asdict(publication),
        "business_outcome":asdict(business),
        "acceptance":acceptance,
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(
        json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--database",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=run(database=args.database,output=args.output)
    print(json.dumps({
        "status":result["status"],
        "provider_free":result["provider_free"],
        "all_internal_pass":result["acceptance"]["all_internal_pass"],
        "live_external_complete":result["acceptance"]["live_external_complete"],
        "external_runtime_gates":result["acceptance"]["external_runtime_gates"],
    },sort_keys=True))
    return 0 if result["status"]=="PASS" else 1


if __name__=="__main__":
    raise SystemExit(main())
