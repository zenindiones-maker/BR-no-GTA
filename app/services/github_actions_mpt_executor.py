from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.github_actions_dispatcher import (
    GitHubActionsDispatcher,
)
from app.services.render_executor_service import (
    AbstractRenderExecutor,
    RenderExecutionResult,
)


@dataclass
class GitHubActionsMptExecutionRequest:
    """
    Solicitação de execução do MoneyPrinterTurbo via GitHub Actions.
    """

    repository: str
    workflow: str
    ref: str
    video_subject: str
    video_script: str
    task_id: str


class GitHubActionsMptExecutor(AbstractRenderExecutor):
    """
    Executor de renderização baseado em GitHub Actions.

    Arquitetura:

        BR
         ↓
        GitHubActionsDispatcher
         ↓
        GitHub Actions
         ↓
        MoneyPrinterTurbo CLI
         ↓
        MP4

    Este executor conhece somente o contrato necessário
    para solicitar a execução remota.
    """

    def __init__(
        self,
        repository: str,
        workflow: str = "render-worker.yml",
        ref: str = "main",
        dispatcher: GitHubActionsDispatcher | None = None,
    ) -> None:
        if not repository:
            raise ValueError(
                "O repositório GitHub é obrigatório."
            )

        if not workflow:
            raise ValueError(
                "O workflow GitHub é obrigatório."
            )

        if not ref:
            raise ValueError(
                "A referência Git é obrigatória."
            )

        self.repository = repository
        self.workflow = workflow
        self.ref = ref
        self.dispatcher = dispatcher

    def execute(
        self,
        render_job: dict[str, Any],
    ) -> RenderExecutionResult:
        """
        Solicita a execução do Render Job no GitHub Actions.

        Neste estágio o método somente despacha o workflow.

        Acompanhamento do run, download do artifact e validação
        do MP4 serão implementados nas próximas camadas.
        """

        if not isinstance(render_job, dict) or not render_job:
            raise ValueError(
                "O render job informado é inválido."
            )

        if self.dispatcher is None:
            raise RuntimeError(
                "O dispatcher do GitHub Actions não está configurado."
            )

        video_subject = render_job.get("video_subject")
        video_script = render_job.get("video_script")
        task_id = render_job.get("task_id")

        if not video_subject:
            raise ValueError(
                "O assunto do vídeo é obrigatório."
            )

        if not video_script:
            raise ValueError(
                "O roteiro do vídeo é obrigatório."
            )

        if not task_id:
            raise ValueError(
                "O task_id do render é obrigatório."
            )

        self.dispatcher.dispatch(
            repository=self.repository,
            workflow=self.workflow,
            ref=self.ref,
            inputs={
                "video_subject": str(video_subject),
                "video_script": str(video_script),
                "task_id": str(task_id),
            },
        )

        return RenderExecutionResult(
            success=False,
            output_path=None,
            error=(
                "GitHub Actions foi acionado; "
                "o acompanhamento do render ainda não foi implementado."
            ),
        )
