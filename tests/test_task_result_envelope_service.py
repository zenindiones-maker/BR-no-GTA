from pathlib import Path
from app.services.task_result_envelope_service import DependencyArtifactMissing, build_task_result_envelope, load_task_result_envelope, persist_task_result_envelope

def test_task_result_envelope_persists_hash_lineage_and_refs(tmp_path: Path):
    envelope = build_task_result_envelope(
        mission_id="mission-1", task_id="profile", capability_id="cap.profile",
        agent_id="agent-a", skill_id="profile-skill", executor_binding="module.execute",
        status="COMPLETED", started_at="2026-09-23T00:00:00+00:00",
        completed_at="2026-09-23T00:00:01+00:00", elapsed_ms=1000.0,
        result={"output":"profile complete","evidence_refs":["artifact:profile.json"],"candidate_sha":"a"*40},
        source_task_ids=(), authorization_id="auth-1",
    )
    record = persist_task_result_envelope(envelope, artifact_dir=tmp_path, index=1)
    loaded = load_task_result_envelope(artifact_dir=tmp_path, task_result_ref=record["task_result_ref"])
    assert loaded["content_sha256"] == envelope.content_sha256
    assert loaded["authorization_lineage_ref"] == "authorization:auth-1"
    assert "git-commit:" + "a"*40 in loaded["output_artifact_refs"]
    assert "artifact:profile.json" in loaded["evidence_refs"]

def test_dependency_missing_error_is_explicit():
    exc = DependencyArtifactMissing(task_id="review", dependency_task_id="candidate", resolution_attempts=("result-snapshot:candidate",))
    text = str(exc)
    assert "DEPENDENCY_ARTIFACT_MISSING" in text
    assert "TASK_ID=review" in text
    assert "MISSING_DEPENDENCY_TASK_ID=candidate" in text
