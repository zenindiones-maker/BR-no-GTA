from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class RenderExecutionResult:
    success: bool
    output_path: str | None = None
    error: str | None = None


class AbstractRenderExecutor(ABC):
    """Contrato para qualquer engine responsável por executar um Render Job."""

    @abstractmethod
    def execute(self, render_job: dict[str, Any]) -> RenderExecutionResult:
        """Executa um Render Job e retorna o resultado da execução."""
        raise NotImplementedError


class NullRenderExecutor(AbstractRenderExecutor):
    """Executor nulo usado enquanto nenhuma engine real está configurada."""

    def execute(self, render_job: dict[str, Any]) -> RenderExecutionResult:
        if not isinstance(render_job, dict) or not render_job:
            raise ValueError("O render job informado é inválido.")

        return RenderExecutionResult(
            success=False,
            output_path=None,
            error="Nenhum executor de renderização está configurado.",
        )
