from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.github_actions_artifact_service import (
    GitHubActionsArtifactService,
)
from app.services.github_actions_dispatcher import (
    GitHubActionsDispatcher,
)
from app.services.github_actions_run_watcher import (
    GitHubActionsRunWatcher,
)
from app.services.mpt_render_request_service import (
    build_mpt_render_request,
)
from app.services.render_artifact_validator import (
    RenderArtifactValidator,
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

    Fluxo:

        Render Job
             ↓
        dispatch
             ↓
        run_id
             ↓
        watcher
             ↓
        artifact download
             ↓
        localizar MP4
             ↓
        validar MP4
             ↓
        RenderExecutionResult
    """

    def __init__(
        self,
        repository: str,
        workflow: str = "render-worker.yml",
        ref: str = "main",
        dispatcher: GitHubActionsDispatcher | None = None,
        watcher: GitHubActionsRunWatcher | None = None,
        artifact_service: GitHubActionsArtifactService | None = None,
        artifact_name: str = "render-output",
        artifact_root: str | Path = "runtime/github-actions-artifacts",
        validator: RenderArtifactValidator | None = None,
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

        if not artifact_name:
            raise ValueError(
                "O nome do artifact GitHub é obrigatório."
            )

        if not artifact_root:
            raise ValueError(
                "O diretório raiz dos artifacts é obrigatório."
            )

        self.repository = repository
        self.workflow = workflow
        self.ref = ref
        self.dispatcher = dispatcher
        self.watcher = watcher
        self.artifact_service = artifact_service
        self.artifact_name = artifact_name
        self.artifact_root = Path(artifact_root)
        self.validator = validator

    @staticmethod
    def _locate_mp4(
        output_dir: Path,
    ) -> Path:
        """
        Localiza exatamente um MP4 dentro do artifact baixado.

        A busca é recursiva porque o GitHub Actions pode preservar
        diretórios internos do artifact.

        Zero arquivos ou múltiplos arquivos são tratados como erro
        para evitar selecionar silenciosamente o vídeo errado.
        """

        if not output_dir.exists():
            raise RuntimeError(
                "O diretório local do artifact não existe."
            )

        if not output_dir.is_dir():
            raise RuntimeError(
                "O destino local do artifact não é um diretório."
            )

        mp4_files = sorted(
            (
                path
                for path in output_dir.rglob("*")
                if path.is_file()
                and path.suffix.lower() == ".mp4"
            ),
            key=lambda path: str(path),
        )

        if not mp4_files:
            raise RuntimeError(
                "Nenhum arquivo MP4 foi encontrado no artifact."
            )

        if len(mp4_files) > 1:
            paths = ", ".join(
                str(path)
                for path in mp4_files
            )
            raise RuntimeError(
                "Mais de um arquivo MP4 foi encontrado no artifact: "
                f"{paths}"
            )

        return mp4_files[0]

    @staticmethod
    def _build_error_result(
        error: str,
    ) -> RenderExecutionResult:
        return RenderExecutionResult(
            success=False,
            output_path=None,
            error=error,
        )

    def execute(
        self,
        render_job: dict[str, Any],
    ) -> RenderExecutionResult:
        """
        Executa o render remotamente através do GitHub Actions.

        O executor coordena as etapas, mas não conhece detalhes de:
        - ffprobe;
        - GitHub CLI;
        - formato interno do artifact;
        - render queue;
        - banco de dados;
        - YouTube.
        """

        if not isinstance(render_job, dict) or not render_job:
            raise ValueError(
                "O render job informado é inválido."
            )

        if self.dispatcher is None:
            raise RuntimeError(
                "O dispatcher do GitHub Actions não está configurado."
            )

        if self.watcher is None:
            raise RuntimeError(
                "O watcher do GitHub Actions não está configurado."
            )

        if self.artifact_service is None:
            raise RuntimeError(
                "O serviço de artifact do GitHub Actions "
                "não está configurado."
            )

        if self.validator is None:
            raise RuntimeError(
                "O validador do artifact de renderização "
                "não está configurado."
            )

        mpt_request = build_mpt_render_request(
            render_job
        )

        dispatch_result = self.dispatcher.dispatch(
            repository=self.repository,
            workflow=self.workflow,
            ref=self.ref,
            inputs=mpt_request,
        )

        watch_result = self.watcher.wait_for_completion(
            repository=self.repository,
            run_id=dispatch_result.run_id,
        )

        if watch_result.timed_out:
            return self._build_error_result(
                "O workflow GitHub Actions excedeu o timeout "
                f"de acompanhamento. run_id={dispatch_result.run_id}"
            )

        if watch_result.cancelled:
            return self._build_error_result(
                "O workflow GitHub Actions foi cancelado. "
                f"run_id={dispatch_result.run_id}"
            )

        if watch_result.failed:
            return self._build_error_result(
                "O workflow GitHub Actions terminou com falha. "
                f"run_id={dispatch_result.run_id}; "
                f"conclusion={watch_result.conclusion}"
            )

        if not watch_result.succeeded:
            return self._build_error_result(
                "O workflow GitHub Actions terminou em estado "
                "não reconhecido como sucesso. "
                f"run_id={dispatch_result.run_id}; "
                f"status={watch_result.status}; "
                f"conclusion={watch_result.conclusion}"
            )

        output_dir = (
            self.artifact_root
            / str(dispatch_result.run_id)
        )

        try:
            self.artifact_service.download(
                repository=self.repository,
                run_id=dispatch_result.run_id,
                artifact_name=self.artifact_name,
                output_dir=output_dir,
            )
        except Exception as exc:
            return self._build_error_result(
                "Não foi possível baixar o artifact do GitHub Actions: "
                f"{exc}"
            )

        try:
            mp4_path = self._locate_mp4(
                output_dir,
            )
        except RuntimeError as exc:
            return self._build_error_result(
                str(exc)
            )

        validation = self.validator.validate(
            mp4_path,
        )

        if not validation.valid:
            return self._build_error_result(
                "O artifact MP4 foi rejeitado pela validação: "
                f"{validation.error}"
            )

        return RenderExecutionResult(
            success=True,
            output_path=validation.output_path,
            error=None,
        )
