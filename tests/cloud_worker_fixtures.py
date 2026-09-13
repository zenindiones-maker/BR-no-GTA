"""Shared synthetic RenderJob fixture; never production authorization."""

def job():
    return {
        "render_job_id": 1, "video_id": 2, "content_item_id": 3,
        "script_id": 4, "idea_id": 5, "brain_decision_id": "decision-test",
        "execution_id": "execution-test", "authorized_action": "EXECUTION",
        "estimated_duration_seconds": 40,
        "scenes": [{"segment_id": 6, "content_unit_id": 7}],
        "render": {"resolution": "1920x1080", "fps": 30, "container": "mp4", "video_codec": "h264", "audio_codec": "aac"},
        "edit_plan": {
            "version": "1", "content_item_id": 3, "script_id": 4,
            "title": "contract fixture", "objective": "test", "format": "video",
            "duration_seconds": 40,
            "tracks": [{"name": "V1", "kind": "video", "clips": [{
                "segment_id": 6, "media_path": "source.mp4", "track": "V1",
                "start_seconds": 0, "source_start_seconds": 2, "duration_seconds": 40,
            }]}],
        },
    }

