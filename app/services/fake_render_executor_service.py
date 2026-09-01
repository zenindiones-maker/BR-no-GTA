from typing import Any

from app.services.render_executor_service import (
    AbstractRenderExecutor,
    RenderExecutionResult,
)


class FakeRenderExecutor(AbstractRenderExecutor):
    """Executor determinístico para testes da pipeline de renderização."""

    def __init__(
        self,
        *,
        success: bool = True,
        output_path: str | None = "output/fake_render.mp4",
        error: str | None = "Falha simulada no executor.",
    ) -> None:
        self.success = success
        self.output_path = output_path
        self.error = error

    def execute(
        self,
        render_job: dict[str, Any],
    ) -> RenderExecutionResult:
        if not isinstance(render_job, dict) or not render_job:
            raise ValueError("O render job informado é inválido.")

        if self.success:
            return RenderExecutionResult(
                success=True,
                output_path=self.output_path,
                error=None,
            )

        return RenderExecutionResult(
            success=False,
            output_path=None,
            error=self.error,
        )
