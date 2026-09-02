from __future__ import annotations

from unittest.mock import Mock

from app.database.render_queue_repository import (
    enqueue_render_job,
    get_render_job,
)
from app.database.schema import initialize_schema
from app.database.video_repository import get_video, insert_video
from app.services.render_executor_service import (
    AbstractRenderExecutor,
    RenderExecutionResult,
)
from app.services.render_worker_service import (
    process_next_render_job,
)


def _create_queued_render_job() -> int:
    return enqueue_render_job(
        {
            "content_item_id": 1,
            "script_id": 1,
            "idea_id": 1,
            "objective": "Testar execução do Worker.",
            "format": "YouTube editorial",
            "estimated_duration_seconds": 60,
            "status": "queued",
            "job_type": "video_render",
            "queue": "render",
            "attempt": 0,
            "scenes": [
                {
                    "order": 1,
                    "narrative_block": "INTRODUÇÃO",
                    "narration": "Teste de renderização.",
                    "visual_type": "title_card",
                    "visual_description": "Tela de teste.",
                    "duration_seconds": 5,
                    "requirements": [],
                }
            ],
            "audio_requirements": [],
            "visual_requirements": [],
            "render": {
                "resolution": "1920x1080",
                "fps": 30,
                "aspect_ratio": "16:9",
                "container": "mp4",
                "video_codec": "h264",
                "audio_codec": "aac",
            },
        }
    )


def test_worker_preserves_explicit_executor(monkeypatch):
    explicit_executor = Mock(spec=AbstractRenderExecutor)
    orchestration = Mock()

    monkeypatch.setattr(
        "app.services.render_worker_service.execute_next_render_job",
        orchestration,
    )

    process_next_render_job(
        executor=explicit_executor,
    )

    orchestration.assert_called_once_with(
        executor=explicit_executor,
    )


def test_worker_uses_mpt_factory_when_executor_is_not_provided(
    monkeypatch,
):
    mpt_executor = object()
    factory = Mock(return_value=mpt_executor)
    orchestration = Mock()

    monkeypatch.setattr(
        "app.services.render_worker_service.create_money_printer_turbo_executor",
        factory,
    )
    monkeypatch.setattr(
        "app.services.render_worker_service.execute_next_render_job",
        orchestration,
    )

    process_next_render_job()

    factory.assert_called_once_with()
    orchestration.assert_called_once_with(
        executor=mpt_executor,
    )


def test_worker_passes_none_when_mpt_is_not_configured(
    monkeypatch,
):
    factory = Mock(return_value=None)
    orchestration = Mock()

    monkeypatch.setattr(
        "app.services.render_worker_service.create_money_printer_turbo_executor",
        factory,
    )
    monkeypatch.setattr(
        "app.services.render_worker_service.execute_next_render_job",
        orchestration,
    )

    process_next_render_job()

    factory.assert_called_once_with()
    orchestration.assert_called_once_with(
        executor=None,
    )


def test_worker_executes_queued_job_with_mpt_executor(
    monkeypatch,
):
    job_id = _create_queued_render_job()

    mpt_executor = Mock(spec=AbstractRenderExecutor)
    mpt_executor.execute.return_value = RenderExecutionResult(
        success=True,
        output_path="http://127.0.0.1:8080/tasks/video.mp4",
    )

    factory = Mock(return_value=mpt_executor)

    monkeypatch.setattr(
        "app.services.render_worker_service.create_money_printer_turbo_executor",
        factory,
    )

    result = process_next_render_job()

    assert result is not None
    assert result.success is True
    assert result.output_path == (
        "http://127.0.0.1:8080/tasks/video.mp4"
    )

    factory.assert_called_once_with()
    mpt_executor.execute.assert_called_once()

    persisted_job = get_render_job(job_id)

    assert persisted_job is not None
    assert persisted_job["status"] == "completed"
    assert persisted_job["attempt"] == 1
    assert persisted_job["output_path"] == (
        "http://127.0.0.1:8080/tasks/video.mp4"
    )
    assert persisted_job["error"] is None


def test_process_next_render_job_completes_associated_video():
    initialize_schema()

    video_id = insert_video(
        content_item_id=1,
        title="TESTE - Worker fecha Render -> Video",
        status="draft",
    )

    job = {
        "content_item_id": 1,
        "script_id": 1,
        "idea_id": 1,
        "objective": "Testar fechamento do Worker.",
        "format": "YouTube editorial",
        "estimated_duration_seconds": 60,
        "status": "queued",
        "job_type": "video_render",
        "queue": "render",
        "attempt": 0,
        "video_id": video_id,
        "scenes": [
            {
                "order": 1,
                "narrative_block": "INTRODUÇÃO",
                "narration": "Teste de renderização.",
                "visual_type": "title_card",
                "visual_description": "Tela de teste.",
                "duration_seconds": 5,
                "requirements": [],
            }
        ],
        "audio_requirements": [],
        "visual_requirements": [],
        "render": {
            "resolution": "1920x1080",
            "fps": 30,
            "aspect_ratio": "16:9",
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
        },
    }

    job_id = enqueue_render_job(job)

    executor = Mock(spec=AbstractRenderExecutor)
    executor.execute.return_value = RenderExecutionResult(
        success=True,
        output_path="/tmp/rendered-video.mp4",
    )

    result = process_next_render_job(
        executor=executor,
    )

    assert result is not None
    assert result.success is True
    assert result.output_path == "/tmp/rendered-video.mp4"

    persisted_job = get_render_job(job_id)

    assert persisted_job is not None
    assert persisted_job["status"] == "completed"
    assert persisted_job["video_id"] == video_id
    assert persisted_job["attempt"] == 1
    assert persisted_job["output_path"] == "/tmp/rendered-video.mp4"

    persisted_video = get_video(video_id)

    assert persisted_video is not None
    assert persisted_video["status"] == "ready"
    assert persisted_video["file_path"] == "/tmp/rendered-video.mp4"


class FakeMoneyPrinterTurboClient:
    def __init__(self):
        self.created_payload = None
        self.task_ids = []

    def create_video(self, payload):
        self.created_payload = payload
        return {"task_id": "test-task-001"}

    def get_task(self, task_id):
        self.task_ids.append(task_id)
        return {
            "state": 1,
            "videos": [
                "/tmp/mpt-rendered-video.mp4",
            ],
        }


def test_worker_uses_real_mpt_factory_and_executor_without_network(
    monkeypatch,
):
    initialize_schema()

    video_id = insert_video(
        content_item_id=1,
        title="TESTE - Worker -> Factory -> MPT Executor",
        status="draft",
    )

    job = {
        "content_item_id": 1,
        "script_id": 1,
        "idea_id": 1,
        "objective": "Testar integração real do Worker com a factory MPT.",
        "format": "YouTube editorial",
        "estimated_duration_seconds": 60,
        "status": "queued",
        "job_type": "video_render",
        "queue": "render",
        "attempt": 0,
        "video_id": video_id,
        "scenes": [
            {
                "order": 1,
                "narrative_block": "INTRODUÇÃO",
                "narration": "Teste do executor MoneyPrinterTurbo.",
                "visual_type": "title_card",
                "visual_description": "Tela de teste do MPT.",
                "duration_seconds": 5,
                "execution_requirements": [],
            }
        ],
        "audio_requirements": [],
        "visual_requirements": [],
        "render": {
            "resolution": "1920x1080",
            "fps": 30,
            "aspect_ratio": "16:9",
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
        },
    }

    job_id = enqueue_render_job(job)

    fake_client = FakeMoneyPrinterTurboClient()

    monkeypatch.setattr(
        "app.services.money_printer_turbo_factory.MoneyPrinterTurboClient",
        lambda **kwargs: fake_client,
    )

    monkeypatch.setattr(
        "app.services.money_printer_turbo_factory.settings.MPT_BASE_URL",
        "http://127.0.0.1:8080",
    )

    monkeypatch.setattr(
        "app.services.money_printer_turbo_factory.settings.MPT_API_KEY",
        "",
    )

    monkeypatch.setattr(
        "app.services.money_printer_turbo_factory.settings.MPT_TIMEOUT",
        30.0,
    )

    monkeypatch.setattr(
        "app.services.money_printer_turbo_factory.settings.MPT_POLL_INTERVAL",
        0.0,
    )

    monkeypatch.setattr(
        "app.services.money_printer_turbo_factory.settings.MPT_MAX_POLLS",
        3,
    )

    result = process_next_render_job()

    assert result is not None
    assert result.success is True
    assert result.output_path == "/tmp/mpt-rendered-video.mp4"

    assert fake_client.created_payload is not None
    assert fake_client.created_payload["video_language"] == "pt-BR"
    assert fake_client.created_payload["video_count"] == 1
    assert fake_client.created_payload["match_materials_to_script"] is True

    assert fake_client.task_ids == ["test-task-001"]

    persisted_job = get_render_job(job_id)

    assert persisted_job is not None
    assert persisted_job["status"] == "completed"
    assert persisted_job["video_id"] == video_id
    assert persisted_job["attempt"] == 1
    assert persisted_job["output_path"] == "/tmp/mpt-rendered-video.mp4"
    assert persisted_job["error"] is None

    persisted_video = get_video(video_id)

    assert persisted_video is not None
    assert persisted_video["status"] == "ready"
    assert persisted_video["file_path"] == "/tmp/mpt-rendered-video.mp4"
