from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
        GitHub Actions
         ↓
        MoneyPrinterTurbo CLI
         ↓
        MP4

    Este executor não conhece:
    - regras editoriais;
    - geração de roteiro;
    - banco de dados;
    - YouTube;
    - implementação interna do MPT.

    Ele apenas representa a fronteira entre o Render Worker
    e o backend remoto de execução.
    """

    def __init__(
        self,
        repository: str,
        workflow: str = "media-worker.yml",
        ref: str = "main",
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

    def execute(
        self,
        render_job: dict[str, Any],
    ) -> RenderExecutionResult:
        """
        Executa um Render Job através do backend GitHub Actions.

        A implementação de despacho/poll/download será adicionada
        em uma camada própria. Neste primeiro estágio, o contrato
        permanece explícito e testável.
        """

        if not isinstance(render_job, dict) or not render_job:
            raise ValueError(
                "O render job informado é inválido."
            )

        raise NotImplementedError(
            "O despacho para GitHub Actions ainda não foi implementado."
        )
