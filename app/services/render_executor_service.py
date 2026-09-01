from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class RenderExecutionResult:
    success: bool
    output_path: str | None = None
    error: str | None = None


class AbstractRenderExecutor(ABC):
    """Contrato operacional para qualquer engine de renderização."""

    @abstractmethod
    def execute(
        self,
        render_job: dict[str, Any],
    ) -> RenderExecutionResult:
        """
        Executa um Render Job.

        Entrada:
            render_job: Render Job completo e validado.

        Saída:
            RenderExecutionResult contendo sucesso, saída e/ou erro.

        Implementações futuras podem usar FFmpeg, Blender,
        outro engine ou serviço externo.
        """
        raise NotImplementedError


class NullRenderExecutor(AbstractRenderExecutor):
    """
    Executor nulo usado enquanto nenhuma engine real está configurada.
    """

    def execute(
        self,
        render_job: dict[str, Any],
    ) -> RenderExecutionResult:
        if not isinstance(render_job, dict) or not render_job:
            raise ValueError("O render job informado é inválido.")

        return RenderExecutionResult(
            success=False,
            output_path=None,
            error="Nenhum executor de renderização está configurado.",
        )
