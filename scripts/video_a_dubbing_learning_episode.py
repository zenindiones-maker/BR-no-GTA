from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.main import initialize_application
from app.services.harness_learning_service import (
    HarnessEpisode,
    create_learning_candidate,
    persist_episode,
    record_human_correction,
    record_or_reuse_failure_memory,
)

FEEDBACK={
    "global_dubbing_quality":"FAIL",
    "narration_naturalness":"FAIL",
    "narration_fluency":"FAIL",
    "global_pronunciation_status":"FAIL",
    "leonida_pronunciation":"FAIL",
    "proper_noun_pronunciation":"FAIL",
    "technical_pass_but_perceptual_fail":True,
    "human_voice_review":"REJECTED",
    "all_names_and_places_ptbr_required":True,
    "foreign_language_chunks_forbidden":True,
    "source_language_pronunciation_is_not_automatically_ptbr_target":True,
    "official_english_audio_is_identity_evidence_not_brazilian_acoustic_authority":True,
    "ptbr_narration_requires_brazilian_phonological_realization":True,
    "human_approved_ptbr_pronunciation_has_priority":True,
}
EVIDENCE=(
    "github-run:35525920608",
    "github-artifact:10609442706",
    "github-run:35527492016",
    "github-artifact:10610442121",
    "telegram-messages:317-320",
    "telegram-messages:335-349",
    "human-review:2026-09-20-global-dubbing-rejected-twice",
)

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    initialize_application()
    now=datetime.now(timezone.utc).isoformat()
    episode=HarnessEpisode(
        episode_id="episode-video-a-ptbr-pronunciation-reject-20260920",
        goal_id="video-a-next-candidate-20260920-social-vice-city",
        decision_id="human-all-ptbr-pronunciation-review-20260920",
        execution_id="narration-audition-35527492016",
        task_id="video-a-production-readiness-audio",
        agent_id="professional-video-a-worker",
        capability_id="narration.generate.pt-BR",
        domain="production",
        task_class="video-a-narration-readiness",
        started_at=now,
        finished_at=now,
        duration_seconds=0.0,
        status="FAILED",
        actual_outcome={"observed":True,"human_feedback":FEEDBACK},
        outcome_evidence=EVIDENCE,
        input_refs=("candidate:video-a-next-candidate-20260920-social-vice-city",),
        output_refs=("human-voice-review:REJECTED",),
        evidence_refs=EVIDENCE,
        error="Two technically green audio proofs were rejected by the human; names/places were mispronounced and foreign-language chunking is forbidden. The next execution must use continuous pt-BR synthesis for every entity.",
        human_intervention=True,
        qa_results={
            "AUDIO_TECHNICAL_INTEGRITY":"PASS",
            "TEXT_FIDELITY":"NOT_MEASURED_ON_FINAL_MIX",
            "PRONUNCIATION_CORRECTNESS":"FAIL",
            "PROSODY_NATURALNESS":"FAIL",
            "HUMAN_ACCEPTANCE":"REJECTED",
            **FEEDBACK,
        },
        commit_ref=os.environ.get("GITHUB_SHA"),
        run_ref=os.environ.get("GITHUB_RUN_ID"),
        artifact_refs=("github-artifact:10609442706","github-artifact:10610442121"),
        lineage={
            "candidate_id":"video-a-next-candidate-20260920-social-vice-city",
            "pronunciation_run_id":35525920608,
            "pronunciation_artifact_id":10609442706,
            "audition_run_id":35527492016,
            "audition_artifact_id":10610442121,
            "telegram_message_ids":[317,318,319,320,335,336,337,338,339,340,341,342,343,344,345,346,347,348,349],
            "observed_asr_pronunciation_errors":["Leonida Keis","Porte Geliornan","Junglin","Metro Bombing","Dracoan Prich"],
            "old_segment_policy":"microsegment-v1-default",
            "locked_human_profile_segment_policy":"semantic-section-v1",
            "pronunciation_lexicon":"config/pronunciation_lexicon.json",
        },
    )
    persisted=persist_episode(episode)
    correction=record_human_correction(
        context="VIDEO A Voice B production-readiness review after technically green pronunciation proof",
        undesired_behavior="Component-level gap/lexicon checks were treated as quality evidence while the human heard truncation, artificial rhythm, bad prosody and wrong proper nouns.",
        desired_behavior="Inventory the full final script first; select pronunciation targets using BR-no-GTA human approval, official PT-BR acoustic evidence when available, established Brazilian usage, then PT-BR phonological adaptation; treat source-language audio only as secondary identity evidence; synthesize all names inside continuous pt-BR Voice B context; measure final mastered audio text fidelity; and block full render until explicit human approval.",
        evidence_refs=EVIDENCE,
        goal_id=episode.goal_id,
        task_id=episode.task_id,
        affected_agent=episode.agent_id,
        affected_capability=episode.capability_id,
        metadata={"human_feedback":FEEDBACK},
        scope="TASK_CLASS",
    )
    memory=record_or_reuse_failure_memory(
        claim="human perceptual failure overrides technical green; source-language pronunciation is not automatically a pt-BR target; Brazilian phonological realization, full-script pronunciation coverage and final-mix fidelity are mandatory before render",
        domain="production",
        task_class="video-a-narration-readiness",
        failure_pattern="technical-green-perceptual-fail",
        source_episode_id=episode.episode_id,
        evidence_refs=EVIDENCE,
        capability_id=episode.capability_id,
        agent_id=episode.agent_id,
        metadata={"human_feedback":FEEDBACK},
        confidence=1.0,
    )
    candidate=create_learning_candidate(
        candidate_type="SYSTEM_IMPROVEMENT",
        hypothesis="Use one continuous pt-BR synthesis lane for every final-script entity, apply versioned pt-BR synthesis aliases before TTS, require full-script pronunciation coverage, and keep human approval as the only authority for pronunciation/naturalness.",
        domain="production",
        task_class="video-a-narration-readiness",
        source_episode_ids=(episode.episode_id,),
        evidence_refs=EVIDENCE,
        target_agent_id=episode.agent_id,
        target_capability_id=episode.capability_id,
        candidate_version=os.environ.get("GITHUB_SHA") or "global-dubbing-readiness-v1",
        implementation_ref="video-a-production-readiness:quality-first-semantic-section",
        acceptance_criteria={
            "technical_green_does_not_equal_spoken_text_correct":True,
            "pronunciation_validation_must_cover_entire_final_script":True,
            "human_perceptual_fail_overrides_technical_pass":True,
            "proper_noun_inventory_must_run_before_synthesis":True,
            "next_audio_policy_must_differ_from_rejected_default":True,
            "human_review_required":True,
            "full_render_forbidden":True,
            "all_synthesis_locale_ptbr":True,
            "foreign_language_chunks_forbidden":True,
            "source_language_pronunciation_is_not_automatically_ptbr_target":True,
            "official_english_audio_is_identity_evidence_not_brazilian_acoustic_authority":True,
            "ptbr_narration_requires_brazilian_phonological_realization":True,
            "human_approved_ptbr_pronunciation_has_priority":True,
            "target_locale":"pt-BR",
        },
    )
    result={
        "status":"PASS",
        "FAILURE_OBSERVED":"PASS",
        "CAUSE_IDENTIFIED":"PASS",
        "LEARNING_EPISODE_ID":persisted["episode_id"],
        "LEARNING_CANDIDATE_ID":candidate["candidate_id"],
        "failure_memory_id":memory["memory_id"],
        "correction_id":correction["correction_id"],
        "old_execution_policy":{
            "segment_strategy":"microsegment-v1-default",
            "quality_proxy":"component gap/chunk/lexicon checks",
            "proper_noun_inventory":"partial/manual",
            "final_mix_text_fidelity":"absent",
        },
        "new_execution_policy":{
            "segment_strategy":"semantic-section-v1-default",
            "quality_proxy":"five independent QA dimensions + human acceptance",
            "proper_noun_inventory":"full final script before synthesis",
            "all_entity_synthesis_locale":"pt-BR",
            "foreign_language_chunks":"forbidden",
            "ptbr_alias_lexicon":"config/pronunciation_ptbr_candidate.json",
            "ptbr_pronunciation_policy":"config/pronunciation_ptbr_policy.json",
            "ptbr_research_registry":"config/pronunciation_ptbr_research.json",
            "official_ptbr_dub_reference":"UNCONFIRMED",
            "final_mix_text_fidelity":"required",
        },
        "LEARNING_APPLIED":"PENDING_NEXT_AUDIO",
        "HUMAN_REVIEW":"PENDING",
        "PRODUCTION_READINESS":"FAIL",
        "FULL_RENDER_AUTHORIZED":"NO",
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print("FAILURE_OBSERVED=PASS")
    print("CAUSE_IDENTIFIED=PASS")
    print("LEARNING_CANDIDATE_CREATED=PASS")
    print("EXECUTION_POLICY_CHANGED=PASS")
    print("LEARNING_EPISODE_ID="+persisted["episode_id"])
    print("LEARNING_CANDIDATE_ID="+candidate["candidate_id"])
    print("LEARNING_APPLIED=PENDING_NEXT_AUDIO")
    print("PRODUCTION_READINESS=FAIL")
    print("FULL_RENDER_AUTHORIZED=NO")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
