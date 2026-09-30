from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from app.contracts.youtube_intelligence_contracts import (
    AdvertiserSuitabilityReview,
    HookContract,
    NaturalAdBreakCandidate,
    PackagingVariantSet,
    RetentionBlueprint,
    RetentionEvent,
    VideoPostmortem,
    YouTubePackagingExperiment,
)


RETENTION_EVENT_TYPES=frozenset({
    "INTRO_LOSS","DIP","SPIKE","TOP_MOMENT","GRADUAL_DECAY",
})
PACKAGING_RESULTS=frozenset({"WINNER","PERFORMED_SAME","INCONCLUSIVE"})


def build_hook_contract(**kwargs: Any) -> HookContract:
    return HookContract(**kwargs)


def build_retention_blueprint(
    *,
    hook: HookContract,
    first_value_timestamp: float,
    open_loops: Sequence[str],
    section_payoffs: Sequence[Mapping[str,Any]],
    novelty_cadence_seconds: float | None,
    visual_changes: Sequence[Mapping[str,Any]],
    evidence_reveals: Sequence[Mapping[str,Any]],
    story_progression: Sequence[str],
    re_hooks: Sequence[Mapping[str,Any]],
    cta_positions: Sequence[float],
    ad_break_candidates: Sequence[Mapping[str,Any]],
    ending_payoff: str,
    end_screen_transition: str,
    evidence_refs: Sequence[str],
) -> RetentionBlueprint:
    return RetentionBlueprint(
        hook=hook.to_dict(),
        first_value_timestamp_seconds=first_value_timestamp,
        first_value_timestamp=first_value_timestamp,
        open_loops=tuple(open_loops),
        section_payoffs=tuple(section_payoffs),
        novelty_cadence_seconds=novelty_cadence_seconds,
        visual_changes=tuple(visual_changes),
        evidence_reveals=tuple(evidence_reveals),
        story_progression=tuple(story_progression),
        rehooks=tuple(re_hooks),
        cta_positions=tuple(float(x) for x in cta_positions),
        ad_break_candidates=tuple(ad_break_candidates),
        ending_payoff=ending_payoff,
        end_screen_transition=end_screen_transition,
        evidence_refs=tuple(evidence_refs),
    )


def natural_ad_break_candidates(
    *,
    transitions: Iterable[Mapping[str,Any]],
    video_duration_seconds: float,
    evidence_refs: Sequence[str],
) -> tuple[NaturalAdBreakCandidate,...]:
    if video_duration_seconds < 8*60:
        return ()
    candidates=[]
    for item in transitions:
        timestamp=float(item.get("timestamp_seconds") or -1)
        if timestamp < 0:
            continue
        if item.get("mid_sentence") is True:
            continue
        if item.get("before_immediate_payoff") is True:
            continue
        if str(item.get("transition_type") or "") not in {
            "SECTION_TRANSITION","AUDIO_PAUSE","VISUAL_TRANSITION","COMPLETED_PAYOFF",
        }:
            continue
        candidates.append(NaturalAdBreakCandidate(
            timestamp_seconds=timestamp,
            rationale=str(item.get("reason") or item.get("transition_type") or ""),
            reason=str(item.get("reason") or item.get("transition_type") or ""),
            transition_type=str(item.get("transition_type") or ""),
            mid_sentence=False,
            before_immediate_payoff=False,
            evidence_refs=tuple(evidence_refs),
        ))
    return tuple(candidates)


def advertiser_suitability_review(
    *,
    video_id: str,
    observations: Mapping[str,str],
    categories: Mapping[str,str],
    evidence_refs: Sequence[str],
) -> AdvertiserSuitabilityReview:
    impacts={str(v).upper() for v in categories.values()}
    impact=(
        "HIGH_RISK" if "HIGH" in impacts
        else "MODERATE_RISK" if "MODERATE" in impacts
        else "LOW_RISK" if impacts and impacts <= {"LOW","NONE"}
        else "UNKNOWN"
    )
    return AdvertiserSuitabilityReview(
        video_id=video_id,
        title_risk=str(observations.get("title") or "UNKNOWN"),
        thumbnail_risk=str(observations.get("thumbnail") or "UNKNOWN"),
        first_7s_risk=str(observations.get("first_7_seconds") or "UNKNOWN"),
        first_30s_risk=str(observations.get("first_30_seconds") or "UNKNOWN"),
        categories=dict(categories),
        expected_monetization_impact=impact,
        editorial_truth_preserved=True,
        evidence_refs=tuple(evidence_refs),
    )


def validate_packaging_variant_set(record: PackagingVariantSet) -> dict[str,Any]:
    def _valid_variant(item: Mapping[str,Any]) -> bool:
        required={
            "target_audience","promise","curiosity_mechanism",
            "search_relevance","browse_relevance","evidence_honesty",
            "visual_focal_point","expected_weakness",
        }
        return required.issubset(set(item))
    if not all(_valid_variant(x) for x in record.title_variants):
        raise ValueError("title packaging variant missing required rationale fields")
    if not all(_valid_variant(x) for x in record.thumbnail_variants):
        raise ValueError("thumbnail packaging variant missing required rationale fields")
    return {
        "schema":"PackagingVariantValidation/v1",
        "video_id":record.video_id,
        "title_count":len(record.title_variants),
        "thumbnail_count":len(record.thumbnail_variants),
        "clickbait_optimizer":False,
        "honest_value_representation_required":True,
    }


def build_packaging_experiment(
    *,
    video_id: str,
    variants: Sequence[Mapping[str,Any]],
    experiment_start: str,
    experiment_end: str | None,
    native_result: str,
    watch_time_share_winner: str | None,
    confidence_class: str,
    evidence_refs: Sequence[str],
) -> YouTubePackagingExperiment:
    if native_result not in PACKAGING_RESULTS:
        raise ValueError("native result must be WINNER, PERFORMED_SAME or INCONCLUSIVE")
    return YouTubePackagingExperiment(
        video_id=video_id,
        variants=tuple(variants),
        experiment_start=experiment_start,
        experiment_end=experiment_end,
        native_result=native_result,
        watch_time_share_winner=watch_time_share_winner,
        confidence_class=confidence_class,
        evidence_refs=tuple(evidence_refs),
    )


def build_retention_event(
    *,
    video_id: str,
    event_type: str,
    timestamp_seconds: float,
    script_section: str | None,
    visual_section: str | None,
    audio_section: str | None,
    topic: str | None,
    editing_pattern: str | None,
    hypothesized_cause: str | None,
    evidence_refs: Sequence[str],
) -> RetentionEvent:
    if event_type not in RETENTION_EVENT_TYPES:
        raise ValueError("unsupported retention event type")
    return RetentionEvent(
        video_id=video_id,event_type=event_type,timestamp_seconds=timestamp_seconds,
        script_section=script_section,visual_section=visual_section,
        audio_section=audio_section,topic=topic,editing_pattern=editing_pattern,
        hypothesized_cause=hypothesized_cause,cause_status="HYPOTHESIS",
        evidence_refs=tuple(evidence_refs),
    )


def build_video_postmortem(
    *,
    video_id: str,
    findings: Mapping[str,Any],
    evidence_refs: Sequence[str],
) -> VideoPostmortem:
    return VideoPostmortem(
        video_id=video_id,
        what_worked=tuple(findings.get("what_worked") or ()),
        what_failed=tuple(findings.get("what_failed") or ()),
        viewer_exit_observations=tuple(findings.get("viewer_exit_observations") or ()),
        rewatch_observations=tuple(findings.get("rewatch_observations") or ()),
        traffic_source_findings=tuple(findings.get("traffic_source_findings") or ()),
        packaging_honesty=str(findings.get("packaging_honesty") or "UNKNOWN"),
        revenue_findings=tuple(findings.get("revenue_findings") or ()),
        advertiser_suitability_findings=tuple(findings.get("advertiser_suitability_findings") or ()),
        repeat_candidates=tuple(findings.get("repeat_candidates") or ()),
        retire_candidates=tuple(findings.get("retire_candidates") or ()),
        evidence_refs=tuple(evidence_refs),
    )


def learning_episode_eligibility(
    *,
    postmortem: VideoPostmortem,
    repeated_episode_count: int,
    held_out_evaluation_passed: bool,
    independent_review_passed: bool,
) -> dict[str,Any]:
    eligible=bool(
        repeated_episode_count >= 3
        and held_out_evaluation_passed
        and independent_review_passed
        and postmortem.evidence_refs
    )
    return {
        "schema":"VideoEditingLearningEpisodeEligibility/v1",
        "video_id":postmortem.video_id,
        "verified_episode":bool(postmortem.evidence_refs),
        "repeated_episode_count":int(repeated_episode_count),
        "held_out_evaluation_passed":bool(held_out_evaluation_passed),
        "independent_review_passed":bool(independent_review_passed),
        "skill_candidate_eligible":eligible,
        "auto_promote":False,
        "promotion_authority":"DEEPSEEK_HARNESS_LEARNING_PLANE",
        "single_video_overfitting_allowed":False,
    }
