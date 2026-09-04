from __future__ import annotations

from unittest.mock import Mock

from app.database.render_queue_repository import (
    enqueue_render_job,
    get_render_job,
)
from app.database.schema import initialize_schema
from app.database.content_repository import insert_content_item
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

    content_item_id = insert_content_item(
        title="Conteúdo de teste do Render Worker",
        content_type="video",
        status="draft",
    )

    video_id = insert_video(
        content_item_id=content_item_id,
        title="TESTE - Worker fecha Render -> Video",
        status="draft",
    )

    job = {
        "content_item_id": content_item_id,
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


class FakeRenderExecutor(AbstractRenderExecutor):
    def __init__(self, output_path: str):
        self.output_path = output_path
        self.jobs = []

    def execute(self, render_job):
        self.jobs.append(render_job)
        return RenderExecutionResult(
            success=True,
            output_path=self.output_path,
        )


def test_worker_uses_factory_executor_without_network(
    monkeypatch,
):
    initialize_schema()

    job_id = _create_queued_render_job()

    executor = FakeRenderExecutor(
        "/tmp/mpt-rendered-video.mp4",
    )

    factory = Mock(return_value=executor)

    monkeypatch.setattr(
        "app.services.render_worker_service.create_money_printer_turbo_executor",
        factory,
    )

    result = process_next_render_job()

    assert result is not None
    assert result.success is True
    assert result.output_path == "/tmp/mpt-rendered-video.mp4"

    factory.assert_called_once_with()

    assert len(executor.jobs) == 1
    assert executor.jobs[0]["objective"] == (
        "Testar execução do Worker."
    )

    persisted_job = get_render_job(job_id)

    assert persisted_job is not None
    assert persisted_job["status"] == "completed"
    assert persisted_job["attempt"] == 1
    assert persisted_job["output_path"] == (
        "/tmp/mpt-rendered-video.mp4"
    )
    assert persisted_job["error"] is None


def test_worker_preserves_editorial_content_for_executor(
    monkeypatch,
):
    initialize_schema()

    content_item_id = insert_content_item(
        title="Conteúdo de teste do Render Worker",
        content_type="video",
        status="draft",
    )

    video_id = insert_video(
        content_item_id=content_item_id,
        title="TESTE - contrato editorial BR -> Executor",
        status="draft",
    )

    job = {
        "content_item_id": content_item_id,
        "script_id": 42,
        "idea_id": 24,
        "objective": (
            "Informar o público sobre uma nova informação "
            "confirmada de GTA 6"
        ),
        "format": "YouTube editorial",
        "estimated_duration_seconds": 120,
        "status": "queued",
        "job_type": "video_render",
        "queue": "render",
        "attempt": 0,
        "video_id": video_id,
        "scenes": [
            {
                "order": 1,
                "narrative_block": "INTRODUÇÃO",
                "narration": (
                    "Uma nova informação sobre GTA 6 "
                    "chamou a atenção da comunidade."
                ),
                "visual_type": "title_card",
                "visual_description": (
                    "Logo de GTA 6 com manchete de última hora."
                ),
                "duration_seconds": 10,
                "execution_requirements": [],
            },
            {
                "order": 2,
                "narrative_block": "CONTEXTO",
                "narration": (
                    "O contexto ajuda a entender por que "
                    "essa informação é relevante."
                ),
                "visual_type": "gameplay",
                "visual_description": (
                    "Gameplay de GTA 6 mostrando uma área urbana."
                ),
                "duration_seconds": 10,
                "execution_requirements": [],
            },
            {
                "order": 3,
                "narrative_block": "CONSEQUÊNCIA",
                "narration": (
                    "A possível consequência pode afetar "
                    "a expectativa dos jogadores."
                ),
                "visual_type": "gameplay",
                "visual_description": (
                    "Gameplay com gráfico destacando a informação."
                ),
                "duration_seconds": 10,
                "execution_requirements": [],
            },
        ],
        "audio_requirements": [],
        "visual_requirements": [
            "Usar imagens relacionadas a GTA 6.",
        ],
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

    executor = FakeRenderExecutor(
        "/tmp/mpt-rendered-video.mp4",
    )

    factory = Mock(return_value=executor)

    monkeypatch.setattr(
        "app.services.render_worker_service.create_money_printer_turbo_executor",
        factory,
    )

    result = process_next_render_job()

    assert result is not None
    assert result.success is True

    factory.assert_called_once_with()

    assert len(executor.jobs) == 1

    received_job = executor.jobs[0]

    assert received_job["objective"] == (
        "Informar o público sobre uma nova informação "
        "confirmada de GTA 6"
    )

    assert received_job["scenes"][0]["narration"] == (
        "Uma nova informação sobre GTA 6 "
        "chamou a atenção da comunidade."
    )

    assert received_job["scenes"][0]["visual_description"] == (
        "Logo de GTA 6 com manchete de última hora."
    )

    assert received_job["scenes"][1]["narration"] == (
        "O contexto ajuda a entender por que "
        "essa informação é relevante."
    )

    assert received_job["scenes"][1]["visual_description"] == (
        "Gameplay de GTA 6 mostrando uma área urbana."
    )

    assert received_job["scenes"][2]["narration"] == (
        "A possível consequência pode afetar "
        "a expectativa dos jogadores."
    )

    assert received_job["scenes"][2]["visual_description"] == (
        "Gameplay com gráfico destacando a informação."
    )

    assert received_job["visual_requirements"] == [
        "Usar imagens relacionadas a GTA 6.",
    ]

    persisted_job = get_render_job(job_id)

    assert persisted_job is not None
    assert persisted_job["status"] == "completed"
    assert persisted_job["video_id"] == video_id
    assert persisted_job["attempt"] == 1
    assert persisted_job["output_path"] == (
        "/tmp/mpt-rendered-video.mp4"
    )
    assert persisted_job["error"] is None

    persisted_video = get_video(video_id)

    assert persisted_video is not None
    assert persisted_video["status"] == "ready"
    assert persisted_video["file_path"] == (
        "/tmp/mpt-rendered-video.mp4"
    )
