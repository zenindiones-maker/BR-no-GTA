from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


class CloudExecutionContractError(ValueError):
    """Erro de validação do contrato de execução cloud."""


@dataclass(frozen=True)
class ArtifactRef:
    """Referência a um artefato de entrada ou saída."""

    name: str
    url: str | None = None
    path: str | None = None
    media_type: str | None = None
    sha256: str | None = None

    def validate(self) -> None:
        if not self.name.strip():
            raise CloudExecutionContractError(
                "ArtifactRef.name é obrigatório."
            )

        if not self.url and not self.path:
            raise CloudExecutionContractError(
                f"ArtifactRef {self.name!r} precisa de url ou path."
            )


@dataclass(frozen=True)
class HarnessContext:
    """Contexto estratégico autorizado pelo Harness."""

    topic: str
    objective: str
    format: str
    target_duration_seconds: float
    priority: str
    confidence: float
    instructions: str = ""
    sources: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.topic.strip():
            raise CloudExecutionContractError(
                "HarnessContext.topic é obrigatório."
            )

        if not self.objective.strip():
            raise CloudExecutionContractError(
                "HarnessContext.objective é obrigatório."
            )

        if not self.format.strip():
            raise CloudExecutionContractError(
                "HarnessContext.format é obrigatório."
            )

        if self.target_duration_seconds <= 0:
            raise CloudExecutionContractError(
                "target_duration_seconds precisa ser positivo."
            )

        if not 0 <= self.confidence <= 1:
            raise CloudExecutionContractError(
                "confidence precisa estar entre 0 e 1."
            )


@dataclass(frozen=True)
class CloudExecutionRequest:
    """
    Contrato único entre BR/Harness e o worker cloud.

    O runner não possui autoridade editorial.
    Ele somente executa o que este contrato autoriza.
    """

    execution_id: str
    authorized_action: str
    worker: str
    harness_context: HarnessContext
    input_artifacts: tuple[ArtifactRef, ...] = ()
    output_artifacts: tuple[ArtifactRef, ...] = ()

    def validate(self) -> None:
        if not self.execution_id.strip():
            raise CloudExecutionContractError(
                "execution_id é obrigatório."
            )

        if not self.authorized_action.strip():
            raise CloudExecutionContractError(
                "authorized_action é obrigatório."
            )

        if not self.worker.strip():
            raise CloudExecutionContractError(
                "worker é obrigatório."
            )

        self.harness_context.validate()

        for artifact in self.input_artifacts:
            artifact.validate()

        for artifact in self.output_artifacts:
            artifact.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)


@dataclass(frozen=True)
class CloudExecutionResult:
    """Resultado devolvido pelo worker ao BR."""

    execution_id: str
    job_id: int
    authorized_action: str
    worker: str
    status: str
    output_artifacts: tuple[ArtifactRef, ...] = ()
    result_manifest: dict[str, Any] | None = None
    error: str | None = None

    def validate(self) -> None:
        if not self.execution_id.strip():
            raise CloudExecutionContractError(
                "CloudExecutionResult.execution_id é obrigatório."
            )

        if self.job_id <= 0:
            raise CloudExecutionContractError(
                "CloudExecutionResult.job_id precisa ser positivo."
            )

        if not self.status.strip():
            raise CloudExecutionContractError(
                "CloudExecutionResult.status é obrigatório."
            )

        for artifact in self.output_artifacts:
            artifact.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)
