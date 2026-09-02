import json

import pytest

from app.services.money_printer_turbo_executor import (
    MoneyPrinterTurboExecutor,
)
from app.services.render_executor_service import (
    AbstractRenderExecutor,
    RenderExecutionResult,
)


def _create_render_job():
    return {
        "id": 42,
        "content_item_id": 1,
        "script_id": 2,
        "idea_id": 3,
        "objective": "Informar sobre GTA 6",
        "format": "short",
        "estimated_duration_seconds": 30,
        "status": "running",
        "scenes": [
            {
                "order": 1,
                "narrative_block": "Introdução",
                "narration": "GTA 6 recebeu uma nova informação importante.",
                "visual_type": "title_card",
                "visual_description": "GTA 6 e Rockstar Games",
                "duration_seconds": 10,
                "execution_requirements": [
                    "Reforçar visualmente a abertura."
                ],
            },
            {
                "order": 2,
                "narrative_block": "Contexto",
                "narration": "A informação muda a expectativa sobre o jogo.",
                "visual_type": "gameplay",
                "visual_description": "Gameplay de GTA 6 em Vice City",
                "duration_seconds": 20,
                "execution_requirements": [
                    "Mostrar elementos relacionados ao contexto."
                ],
            },
        ],
        "audio_requirements": [
            "Utilizar narração clara e inteligível.",
        ],
        "visual_requirements": [
            {
                "type": "context",
                "description": "Utilizar imagens relacionadas ao tema.",
            }
        ],
        "render": {
            "resolution": "1920x1080",
            "fps": 30,
            "aspect_ratio": "16:9",
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
        },
        "job_type": "video_render",
        "queue": "render",
        "attempt": 1,
    }


class FakeMPTClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posted_payload = None
        self.task_id = "mpt-task-123"
        self.poll_calls = 0

    def create_video(self, payload):
        self.posted_payload = payload
        return {"task_id": self.task_id}

    def get_task(self, task_id):
        assert task_id == self.task_id

        response = self.responses[
            min(self.poll_calls, len(self.responses) - 1)
        ]

        self.poll_calls += 1
        return response


def test_executor_implements_abstract_contract():
    client = FakeMPTClient(
        [
            {
                "task_id": "mpt-task-123",
                "state": 1,
                "videos": ["http://mpt.local/tasks/final.mp4"],
            }
        ]
    )

    executor = MoneyPrinterTurboExecutor(
        client=client,
        poll_interval=0,
        max_polls=3,
    )

    assert isinstance(executor, AbstractRenderExecutor)


def test_executor_translates_render_job_to_mpt_payload():
    client = FakeMPTClient(
        [
            {
                "task_id": "mpt-task-123",
                "state": 1,
                "videos": ["http://mpt.local/tasks/final.mp4"],
            }
        ]
    )

    executor = MoneyPrinterTurboExecutor(
        client=client,
        poll_interval=0,
        max_polls=3,
    )

    result = executor.execute(_create_render_job())

    assert result.success is True
    assert result.output_path == "http://mpt.local/tasks/final.mp4"

    payload = client.posted_payload

    assert payload["video_subject"] == "Informar sobre GTA 6."
    assert payload["video_script"] == (
        "GTA 6 recebeu uma nova informação importante.\n\n"
        "A informação muda a expectativa sobre o jogo."
    )
    assert payload["video_terms"] == [
        "GTA 6 e Rockstar Games",
        "Gameplay de GTA 6 em Vice City",
    ]

    assert payload["video_aspect"] == "landscape"
    assert payload["video_count"] == 1
    assert payload["video_source"] == "pexels"
    assert payload["subtitle_enabled"] is True


def test_executor_polls_until_task_is_complete():
    client = FakeMPTClient(
        [
            {
                "task_id": "mpt-task-123",
                "state": 4,
                "progress": 25,
            },
            {
                "task_id": "mpt-task-123",
                "state": 4,
                "progress": 75,
            },
            {
                "task_id": "mpt-task-123",
                "state": 1,
                "videos": ["http://mpt.local/tasks/final.mp4"],
            },
        ]
    )

    executor = MoneyPrinterTurboExecutor(
        client=client,
        poll_interval=0,
        max_polls=5,
    )

    result = executor.execute(_create_render_job())

    assert result.success is True
    assert result.output_path == "http://mpt.local/tasks/final.mp4"
    assert client.poll_calls == 3


def test_executor_maps_mpt_failed_state():
    client = FakeMPTClient(
        [
            {
                "task_id": "mpt-task-123",
                "state": -1,
                "failed_stage": "video",
                "error": "Falha no render do vídeo.",
            }
        ]
    )

    executor = MoneyPrinterTurboExecutor(
        client=client,
        poll_interval=0,
        max_polls=3,
    )

    result = executor.execute(_create_render_job())

    assert result.success is False
    assert result.output_path is None
    assert "Falha no render do vídeo." in result.error


def test_executor_rejects_missing_task_id():
    class ClientWithoutTaskId:
        def create_video(self, payload):
            return {}

        def get_task(self, task_id):
            raise AssertionError("Não deveria consultar task inexistente.")

    executor = MoneyPrinterTurboExecutor(
        client=ClientWithoutTaskId(),
        poll_interval=0,
        max_polls=3,
    )

    result = executor.execute(_create_render_job())

    assert result.success is False
    assert result.output_path is None
    assert "task_id" in result.error


def test_executor_rejects_poll_timeout():
    client = FakeMPTClient(
        [
            {
                "task_id": "mpt-task-123",
                "state": 4,
                "progress": 50,
            }
        ]
    )

    executor = MoneyPrinterTurboExecutor(
        client=client,
        poll_interval=0,
        max_polls=2,
    )

    result = executor.execute(_create_render_job())

    assert result.success is False
    assert result.output_path is None
    assert "limite" in result.error.lower()
    assert client.poll_calls == 2


def test_executor_requires_video_output_on_completed_task():
    client = FakeMPTClient(
        [
            {
                "task_id": "mpt-task-123",
                "state": 1,
                "videos": [],
                "combined_videos": [],
            }
        ]
    )

    executor = MoneyPrinterTurboExecutor(
        client=client,
        poll_interval=0,
        max_polls=3,
    )

    result = executor.execute(_create_render_job())

    assert result.success is False
    assert result.output_path is None
    assert "saída" in result.error.lower()


def test_executor_converts_client_exception_to_failed_result():
    class FailingClient:
        def create_video(self, payload):
            raise RuntimeError("MPT indisponível.")

        def get_task(self, task_id):
            raise AssertionError("Não deveria consultar task.")

    executor = MoneyPrinterTurboExecutor(
        client=FailingClient(),
        poll_interval=0,
        max_polls=3,
    )

    result = executor.execute(_create_render_job())

    assert isinstance(result, RenderExecutionResult)
    assert result.success is False
    assert result.output_path is None
    assert "MPT indisponível." in result.error


@pytest.mark.parametrize(
    "invalid_job",
    [
        None,
        {},
        [],
        "invalid",
    ],
)
def test_executor_rejects_invalid_render_job(invalid_job):
    client = FakeMPTClient([])

    executor = MoneyPrinterTurboExecutor(
        client=client,
        poll_interval=0,
        max_polls=3,
    )

    with pytest.raises(ValueError, match="render job"):
        executor.execute(invalid_job)
