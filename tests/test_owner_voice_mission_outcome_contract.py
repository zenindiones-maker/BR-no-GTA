from pathlib import Path


def test_owner_voice_mission_must_not_report_success_when_quality_blocks_delivery():
    workflow = Path(".github/workflows/owner-voice-single-human-clone.yml").read_text()
    assert "Enforce audition delivery outcome" in workflow
    assert "MISSION_FAILED_QUALITY_GATES" in workflow
    assert "MISSION_FAILED_GENERATION" in workflow
    assert "HUMAN_APPROVAL=PENDING" in workflow
    assert "MISSION_COMPLETE=FALSE" in workflow


def test_delivery_must_be_confirmed_before_audition_step_can_pass():
    workflow = Path(".github/workflows/owner-voice-single-human-clone.yml").read_text()
    assert "id: reference_delivery" in workflow
    assert "id: critical_delivery" in workflow
    assert 'if [ "$CRITICAL_DELIVERY_RESULT" != success ]; then' in workflow
    assert 'if [ "$REFERENCE_DELIVERY_RESULT" != success ]; then' in workflow
    assert 'GENERATION_RESULT: ${{ steps.generate.outcome }}' in workflow


def test_pr_checks_cannot_replace_a_pending_authorized_delivery_run():
    workflow = Path(".github/workflows/owner-voice-single-human-clone.yml").read_text()
    # A pull_request validation was replacing the queued explicit push request;
    # GitHub concurrency 'cancel-in-progress: false' alone does not protect it.
    assert "group: br-owner-v1-single-human-clone-${{ github.event_name }}" in workflow
    assert "cancel-in-progress: false" in workflow


def test_explicit_request_detection_reads_checkout_diff_not_truncated_event():
    workflow = Path(".github/workflows/owner-voice-single-human-clone.yml").read_text()
    # GitHub App-created pushes may omit changed paths from the event payload;
    # only a proven change to the exact authorized request can start inference.
    assert "fetch-depth: 2" in workflow
    assert "git diff --name-only HEAD^ HEAD" in workflow
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in workflow
