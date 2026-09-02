from __future__ import annotations

import time
from typing import Any, Protocol

from app.services.render_executor_service import (
    AbstractRenderExecutor,
    RenderExecutionResult,
)


class MoneyPrinterTurboClient(Protocol):
    """
    Contrato mínimo necessário para comunicação com o MPT.

    A implementação HTTP real será adicionada separadamente.
    """

    def create_video(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        ...

    def get_task(
        self,
        task_id: str,
    ) -> dict[str, Any]:
        ...


class MoneyPrinterTurboExecutor(AbstractRenderExecutor):
    """
    Executor de Render Job usando o MoneyPrinterTurbo.

    O BR continua sendo responsável pela especificação editorial.
    O MPT é responsável pela produção audiovisual.

    Este executor apenas traduz o contrato do BR para o contrato
    de entrada/saída do MPT.
    """

    MPT_STATE_FAILED = -1
    MPT_STATE_COMPLETE = 1
    MPT_STATE_PROCESSING = 4

    def __init__(
        self,
        *,
        client: MoneyPrinterTurboClient,
        poll_interval: float = 2.0,
        max_polls: int = 300,
    ) -> None:
        if client is None:
            raise ValueError("client é obrigatório.")

        if poll_interval < 0:
            raise ValueError(
                "poll_interval deve ser maior ou igual a zero."
            )

        if max_polls < 1:
            raise ValueError(
                "max_polls deve ser maior que zero."
            )

        self.client = client
        self.poll_interval = poll_interval
        self.max_polls = max_polls

    def execute(
        self,
        render_job: dict[str, Any],
    ) -> RenderExecutionResult:
        """
        Executa um Render Job através do MoneyPrinterTurbo.

        O método não conhece banco, fila ou Video.
        Seu único contrato externo é RenderExecutionResult.
        """

        self._validate_render_job(render_job)

        try:
            payload = self._build_mpt_payload(render_job)

            response = self.client.create_video(payload)

            task_id = self._extract_task_id(response)

            if task_id is None:
                return RenderExecutionResult(
                    success=False,
                    output_path=None,
                    error="MoneyPrinterTurbo não retornou task_id.",
                )

            return self._poll_task(task_id)

        except Exception as exc:
            return RenderExecutionResult(
                success=False,
                output_path=None,
                error=str(exc),
            )

    def _poll_task(
        self,
        task_id: str,
    ) -> RenderExecutionResult:
        """
        Aguarda a conclusão da task do MoneyPrinterTurbo.
        """

        for _ in range(self.max_polls):
            response = self.client.get_task(task_id)

            state = response.get("state")

            if state == self.MPT_STATE_COMPLETE:
                output_path = self._extract_output_path(response)

                if not output_path:
                    return RenderExecutionResult(
                        success=False,
                        output_path=None,
                        error=(
                            "MoneyPrinterTurbo concluiu a task, "
                            "mas não retornou saída de vídeo."
                        ),
                    )

                return RenderExecutionResult(
                    success=True,
                    output_path=output_path,
                    error=None,
                )

            if state == self.MPT_STATE_FAILED:
                error = (
                    response.get("error")
                    or response.get("failed_stage")
                    or "MoneyPrinterTurbo falhou na produção do vídeo."
                )

                return RenderExecutionResult(
                    success=False,
                    output_path=None,
                    error=str(error),
                )

            if state == self.MPT_STATE_PROCESSING:
                if self.poll_interval > 0:
                    time.sleep(self.poll_interval)

                continue

            return RenderExecutionResult(
                success=False,
                output_path=None,
                error=(
                    "MoneyPrinterTurbo retornou estado "
                    f"desconhecido: {state}."
                ),
            )

        return RenderExecutionResult(
            success=False,
            output_path=None,
            error=(
                "MoneyPrinterTurbo não concluiu a task "
                "dentro do limite de polling."
            ),
        )

    @staticmethod
    def _extract_task_id(
        response: dict[str, Any],
    ) -> str | None:
        if not isinstance(response, dict):
            return None

        task_id = response.get("task_id")

        if not isinstance(task_id, str):
            return None

        task_id = task_id.strip()

        return task_id or None

    @staticmethod
    def _extract_output_path(
        response: dict[str, Any],
    ) -> str | None:
        if not isinstance(response, dict):
            return None

        for field in ("videos", "combined_videos"):
            outputs = response.get(field)

            if not isinstance(outputs, list):
                continue

            for output in outputs:
                if isinstance(output, str) and output.strip():
                    return output.strip()

        return None

    @staticmethod
    def _build_mpt_payload(
        render_job: dict[str, Any],
    ) -> dict[str, Any]:
        scenes = render_job["scenes"]

        script_parts = []
        video_terms = []

        for scene in scenes:
            narration = str(scene["narration"]).strip()

            if narration:
                script_parts.append(narration)

            visual_description = str(
                scene["visual_description"]
            ).strip()

            if visual_description:
                video_terms.append(visual_description)

        video_script = "\n\n".join(script_parts)

        if not video_script:
            raise ValueError(
                "Render job não possui narração utilizável."
            )

        if not video_terms:
            raise ValueError(
                "Render job não possui termos visuais utilizáveis."
            )

        objective = str(render_job["objective"]).strip()

        if not objective:
            raise ValueError(
                "Render job não possui objetivo editorial."
            )

        video_subject = objective.rstrip(".!? ") + "."

        return {
            "video_subject": video_subject,
            "video_script": video_script,
            "video_terms": video_terms,
            "video_aspect": "landscape",
            "video_fit_mode": "cover",
            "video_concat_mode": "random",
            "video_clip_duration": 5,
            "video_clip_speed": 1.0,
            "match_materials_to_script": True,
            "video_count": 1,
            "video_source": "pexels",
            "video_language": "pt-BR",
            "voice_volume": 1.0,
            "voice_rate": 1.0,
            "bgm_type": "random",
            "bgm_volume": 0.2,
            "subtitle_enabled": True,
            "n_threads": 2,
        }

    @staticmethod
    def _validate_render_job(
        render_job: dict[str, Any],
    ) -> None:
        if not isinstance(render_job, dict) or not render_job:
            raise ValueError("O render job informado é inválido.")

        required_fields = (
            "content_item_id",
            "script_id",
            "idea_id",
            "objective",
            "format",
            "estimated_duration_seconds",
            "scenes",
            "audio_requirements",
            "visual_requirements",
            "render",
        )

        for field in required_fields:
            if field not in render_job:
                raise ValueError(
                    "O render job não possui o campo obrigatório: "
                    f"{field}."
                )

        scenes = render_job.get("scenes")

        if not isinstance(scenes, list) or not scenes:
            raise ValueError(
                "O render job precisa possuir cenas."
            )

        required_scene_fields = (
            "order",
            "narrative_block",
            "narration",
            "visual_type",
            "visual_description",
            "duration_seconds",
            "execution_requirements",
        )

        for scene in scenes:
            if not isinstance(scene, dict):
                raise ValueError(
                    "Cada cena do render job deve ser um objeto válido."
                )

            for field in required_scene_fields:
                if field not in scene:
                    raise ValueError(
                        "A cena não possui o campo obrigatório: "
                        f"{field}."
                    )
