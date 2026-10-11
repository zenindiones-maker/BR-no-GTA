from pathlib import Path


def test_owner_voice_mission_must_not_report_success_when_quality_blocks_delivery():
    workflow = Path(".github/workflows/owner-voice-single-human-clone.yml").read_text()
    assert "Enforce audition delivery outcome" in workflow
    assert "MISSION_FAILED_QUALITY_GATES" in workflow
    assert "MISSION_COMPLETE=FALSE" in workflow
