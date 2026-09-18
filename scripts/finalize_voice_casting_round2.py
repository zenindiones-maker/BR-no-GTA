from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.database.schema import initialize_schema
from app.services.harness_learning_service import HarnessEpisode, persist_episode, record_memory


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--proof-dir",type=Path,required=True)
    parser.add_argument("--feedback",type=Path,required=True)
    parser.add_argument("--checkpoint",type=Path,required=True)
    parser.add_argument("--source-run-id",type=int,required=True)
    parser.add_argument("--source-artifact-id",type=int,required=True)
    args=parser.parse_args()

    proof=args.proof_dir
    feedback=json.loads(args.feedback.read_text(encoding="utf-8"))
    checkpoint=json.loads(args.checkpoint.read_text(encoding="utf-8"))
    manifest=json.loads((proof/"voice-casting-round2-manifest.json").read_text(encoding="utf-8"))
    prosody=json.loads((proof/"prosody-window-benchmark.json").read_text(encoding="utf-8"))
    boundary=json.loads((proof/"boundary-artifact-audit.json").read_text(encoding="utf-8"))
    rates=json.loads((proof/"rate-benchmark.json").read_text(encoding="utf-8"))

    if manifest.get("status")!="HUMAN_FINAL_SELECTION_REQUIRED":
        raise SystemExit("ROUND2_CHECKPOINT_MANIFEST_INVALID")
    if prosody.get("status")!="PASS" or rates.get("status")!="PASS" or boundary.get("status")!="PASS":
        raise SystemExit("ROUND2_CHECKPOINT_TECHNICAL_STATUS_INVALID")
    if manifest.get("selected_blind_ids")!=["Voice B","Voice C"]:
        raise SystemExit("ROUND2_CHECKPOINT_BLIND_IDS_INVALID")
    if manifest.get("identity_revealed") is not False:
        raise SystemExit("ROUND2_CHECKPOINT_IDENTITY_LEAK")

    sample_files=sorted((proof/"samples").glob("*.mp3"))
    if len(sample_files)!=22:
        raise SystemExit(f"ROUND2_SAMPLE_COUNT_INVALID:{len(sample_files)}")
    if any(path.stat().st_size<=0 for path in sample_files):
        raise SystemExit("ROUND2_EMPTY_SAMPLE")

    initialize_schema()

    now=_now()
    run_id=os.environ.get("GITHUB_RUN_ID","local-round2-resume")
    head=os.environ.get("GITHUB_SHA","")
    episode_id="episode-"+hashlib.sha256(
        f"{checkpoint['casting_id']}|round2-resume|{args.source_run_id}".encode()
    ).hexdigest()[:24]
    episode=HarnessEpisode(
        episode_id=episode_id,
        goal_id=checkpoint["casting_id"],
        decision_id=f"{checkpoint['casting_id']}:human-top2",
        execution_id=run_id,
        task_id=f"{checkpoint['casting_id']}:round2",
        agent_id="voice-casting-optimizer",
        capability_id="narration.generate.pt-BR",
        domain="audiovisual",
        task_class="voice-casting-round2",
        started_at=now,
        finished_at=now,
        duration_seconds=0.0,
        status="COMPLETED",
        actual_outcome={
            "observed":True,
            "round1_feedback_consumed":True,
            "round2_multicontext":"PASS",
            "prosody_window_benchmark":"PASS",
            "boundary_artifact_audit":"PASS",
            "rate_tuning":"PASS",
            "audio_checkpoint_reused":True,
            "redundant_tts_requests":0,
            "official_voice_promoted":False,
        },
        outcome_evidence=(
            "voice-casting-round2-manifest.json",
            "prosody-window-benchmark.json",
            "boundary-artifact-audit.json",
            "rate-benchmark.json",
            f"github-run:{args.source_run_id}",
            f"github-artifact:{args.source_artifact_id}",
        ),
        output_refs=(
            "voice-casting-round2-manifest.json",
            "human-voice-feedback.json",
        ),
        evidence_refs=(
            ".run001/voice-casting-round1-feedback.json",
            f"github-run:{args.source_run_id}",
            f"github-artifact:{args.source_artifact_id}",
        ),
        artifact_refs=(f"github-artifact:{args.source_artifact_id}",),
        skill_id="ptbr-edge-voice-casting",
        skill_version="ptbr-edge-voice-casting-round2/v1",
        provider="edge-tts@7.2.8",
        human_intervention=True,
        qa_results={
            "multicontext":"PASS",
            "prosody":"PASS",
            "boundary_audit":"PASS",
            "rate_tuning":"PASS",
        },
        cost=0.0,
        latency_seconds=0.0,
        commit_ref=head or None,
        run_ref=run_id,
        source_versions={"edge-tts":"7.2.8"},
        lineage={
            "authority":"deepseek_harness",
            "publication_authority":"NONE",
            "job18_frozen":True,
            "checkpoint_source_run_id":args.source_run_id,
        },
    )
    persisted=persist_episode(episode)
    memory=record_memory(
        memory_type="HUMAN_FEEDBACK",
        claim=(
            "Round 1 human review selected Voice B first and Voice C second; "
            "Voice C received the note melhor_diccao. Round 2 technical variants are "
            "ready for final human selection; no official voice has been promoted."
        ),
        domain="audiovisual",
        task_class="voice-casting-round2",
        source_episode_ids=(episode_id,),
        evidence_refs=(
            ".run001/voice-casting-round1-feedback.json",
            f"github-artifact:{args.source_artifact_id}",
            "voice-casting-round2-manifest.json",
        ),
        agent_id="voice-casting-optimizer",
        capability_id="narration.generate.pt-BR",
        skill_id="ptbr-edge-voice-casting",
        skill_version="ptbr-edge-voice-casting-round2/v1",
        source_versions={"edge-tts":"7.2.8"},
        metadata={
            "rank_order":["Voice B","Voice C"],
            "human_notes":{"Voice C":["melhor_diccao"]},
            "provider_version_staleness_key":"7.2.8",
            "source_run_id":args.source_run_id,
            "source_artifact_id":args.source_artifact_id,
            "official_profile_promoted":False,
        },
        confidence=0.8,
        status="CANDIDATE",
        identity_payload={
            "casting_id":checkpoint["casting_id"],
            "round":1,
            "feedback":feedback["feedback"],
        },
    )
    _write(proof/"learning-plane-evidence.json",{
        "status":"PASS",
        "episode":persisted,
        "memory":memory,
        "provider_version_staleness_key":"7.2.8",
        "official_profile_promoted":False,
        "schema_initialized":True,
    })
    _write(proof/"round2-performance.json",{
        "status":"CHECKPOINT_REUSED",
        "source_run_id":args.source_run_id,
        "source_artifact_id":args.source_artifact_id,
        "audio_file_count":len(sample_files),
        "synthesis_checkpoint_reused":True,
        "redundant_tts_requests":0,
        "round1_audio_repeated":False,
        "note":"Original synthesis/QA occurred in source run; this resume only persisted learning state and delivery evidence.",
    })
    state={
        "version":"voice-casting-round2-state/v1",
        "casting_id":checkpoint["casting_id"],
        "status":"HUMAN_FINAL_SELECTION_REQUIRED",
        "phase":"ROUND2_FINAL_HUMAN_SELECTION",
        "source_run_id":args.source_run_id,
        "source_artifact_id":args.source_artifact_id,
        "audio_checkpoint_reused":True,
        "redundant_tts_requests":0,
        "round1_feedback_consumed":True,
        "round2_multicontext":"PASS",
        "prosody_window_benchmark":"PASS",
        "boundary_artifact_audit":"PASS",
        "rate_tuning":"PASS",
        "learning_plane":"PASS",
        "telegram_delivery":"PENDING",
        "official_profile_promoted":False,
        "required_response_format":manifest["human_gate"]["required_response_format"],
        "identity_revealed":False,
        "job18_unchanged":True,
        "publication_authority_unchanged":True,
        "harness_authority_preserved":True,
    }
    _write(proof/"voice-casting-round2-state.json",state)
    print("ROUND2_AUDIO_CHECKPOINT_REUSED=YES")
    print("REDUNDANT_TTS_REQUESTS=0")
    print("LEARNING_PLANE=PASS")
    print("HUMAN_FINAL_SELECTION_REQUIRED=YES")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
