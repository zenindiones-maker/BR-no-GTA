"""Technical tests only; no synthetic media is accepted as canary evidence."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.services.render_media_materializer import materialize_scenes, MaterializationError
from app.services.media_ingestion import IngestionStatus


def source():
    return dict(asset_ref="remote://media-worker/trailer", source_url="https://www.youtube.com/watch?v=example",
                segment_id=5, content_unit_id=6, source_start_seconds=10,
                source_end_seconds=55, duration_seconds=45)


def test_hydration_preserves_identity_and_deduplicates(tmp_path):
    calls = []
    class Ingestion:
        def ingest(self, url, output):
            calls.append(url)
            output.write_bytes(b"technical fixture")
            return SimpleNamespace(succeeded=True, output_path=output)
    item = source()
    job = dict(scenes=[item], audio_requirements=[dict(item, type="narration")])
    before = deepcopy(job)
    result, evidence = materialize_scenes(job, tmp_path / "input", ingestion=Ingestion(),
        probe=lambda p: dict(format=dict(duration="60"), streams=[dict(codec_type="video"), dict(codec_type="audio")]))
    assert job == before
    assert len(calls) == 1
    assert Path(result["scenes"][0]["media_path"]).is_file()
    for key in item:
        assert result["scenes"][0][key] == item[key]
    assert evidence[0]["sha256"]


def test_missing_source_fails_before_download(tmp_path):
    class Ingestion:
        def ingest(self, *a):
            pytest.fail("Download must not start")
    item = source()
    del item["source_url"]
    with pytest.raises(MaterializationError, match="source_url"):
        materialize_scenes(dict(scenes=[item]), tmp_path, ingestion=Ingestion())


def test_ingestion_failure_is_not_a_placeholder(tmp_path):
    class Ingestion:
        def ingest(self, *a):
            return SimpleNamespace(succeeded=False, output_path=None, status=IngestionStatus.DOWNLOAD_BLOCKED)
    with pytest.raises(MaterializationError, match="DOWNLOAD_BLOCKED"):
        materialize_scenes(dict(scenes=[source()]), tmp_path, ingestion=Ingestion())
    assert not list(tmp_path.rglob("*.mp4"))


def test_bridge_preserves_fields_and_blocks_wrong_lineage(monkeypatch):
    from app.services import production_media_bridge as bridge
    item = source()
    segment = dict(item, id=5)
    plan = dict(content_item_id=1, script_id=2, idea_id=3, scenes=[dict(duration_seconds=45)])
    monkeypatch.setattr(bridge, "get_content_segment", lambda i: segment)
    monkeypatch.setattr(bridge, "get_content_unit", lambda i: dict(content_item_id=1, script_id=2, idea_id=3))
    result = bridge.bind_selected_segments(plan, [5])
    for key in ("asset_ref", "source_url", "source_start_seconds", "source_end_seconds", "segment_id", "content_unit_id"):
        assert result["scenes"][0][key] == item[key]
    assert "media_path" not in result["scenes"][0]
    monkeypatch.setattr(bridge, "get_content_unit", lambda i: dict(content_item_id=99, script_id=2, idea_id=3))
    with pytest.raises(ValueError, match="lineage"):
        bridge.bind_selected_segments(plan, [5])


def test_runtime_vedit_receives_physical_files(monkeypatch, tmp_path):
    from app.workers import audiovisual_worker as worker
    from app.services import render_media_materializer as materializer
    item = dict(source(), order=1, narrative_block="development", narration="Test",
                visual_type="gameplay", visual_description="Test", requirements=[])
    job = dict(render_job_id=1, video_id=2, content_item_id=3, script_id=4, idea_id=5,
               brain_decision_id="test-decision", execution_id="test-execution",
               authorized_action="EXECUTION", estimated_duration_seconds=45,
               title="Test", objective="Test", format="video", scenes=[item],
               audio_requirements=[dict(source(), type="narration")], visual_requirements=[],
               render=dict(resolution="1920x1080", fps=30, container="mp4", video_codec="h264", audio_codec="aac"))
    original = deepcopy(job)
    def hydrate(value, root):
        root.mkdir(parents=True)
        path = root / "source.mp4"
        path.write_bytes(b"technical fixture only")
        value = deepcopy(value)
        for scene in value["scenes"] + value["audio_requirements"]:
            scene.update(media_path=str(path), file_path=str(path))
        return value, []
    def execute(effective, root, output, *, source_job):
        assert source_job == original
        assert worker.validate_job(effective).duration_seconds == 45
        for track in effective["edit_plan"]["tracks"]:
            for clip in track["clips"]:
                assert worker.resolve_asset(clip["media_path"], root).is_file()
        folder = output / "test"
        folder.mkdir(parents=True)
        return folder
    monkeypatch.setattr(materializer, "materialize_scenes", hydrate)
    monkeypatch.setattr(worker, "execute", execute)
    worker.execute_cloud(job, tmp_path / "input", tmp_path / "output")
    assert job == original


def test_async_dispatch_persists_before_return_and_resume_does_not_dispatch(monkeypatch):
    from app.services.github_actions_audiovisual_executor import GitHubActionsAudiovisualExecutor
    from app.services.render_executor_service import RenderExecutionResult
    executor = GitHubActionsAudiovisualExecutor(repository="owner/repo", dispatcher=object(),
        watcher=object(), artifact_service=object(), validator=object(), wait_for_completion=False)
    execution = dict(run_id=123, repository="owner/repo", workflow="render-worker.yml")
    monkeypatch.setattr(executor, "_dispatch", lambda job: execution)
    saved = []
    result = executor.execute({"id": 1}, on_dispatch=saved.append)
    assert result.pending and not result.success and saved == [execution]
    monkeypatch.setattr(executor, "_dispatch", lambda job: pytest.fail("duplicate dispatch"))
    monkeypatch.setattr(executor, "_wait_and_collect", lambda state: RenderExecutionResult(success=True, output_path="cloud.mp4"))
    assert executor.execute({"github_execution": execution}).success
