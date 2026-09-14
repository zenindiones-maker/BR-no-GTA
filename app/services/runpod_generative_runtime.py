from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol

from app.services.generative_media_service import GeneratedMediaRuntimeResult
from app.services.isolated_generative_media_runtime import AUTHORITY_SHAPED_PAYLOAD_KEYS


class RunpodRuntimeFailureReason(str, Enum):
    RUNPOD_UNAVAILABLE = "RUNPOD_UNAVAILABLE"
    RUNPOD_EXECUTION_FAILED = "RUNPOD_EXECUTION_FAILED"
    RUNPOD_RESULT_INVALID = "RUNPOD_RESULT_INVALID"
    BACKEND_IDENTITY_MISMATCH = "BACKEND_IDENTITY_MISMATCH"
    SOURCE_REVISION_MISMATCH = "SOURCE_REVISION_MISMATCH"
    MODEL_SNAPSHOT_MISMATCH = "MODEL_SNAPSHOT_MISMATCH"
    GPU_IDENTITY_MISSING = "GPU_IDENTITY_MISSING"
    RUNTIME_IDENTITY_MISSING = "RUNTIME_IDENTITY_MISSING"
    ARTIFACT_UNAVAILABLE = "ARTIFACT_UNAVAILABLE"
    JOB_IDENTITY_MISMATCH = "JOB_IDENTITY_MISMATCH"


class RunpodRuntimeError(RuntimeError):
    def __init__(self, reason: RunpodRuntimeFailureReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class RunpodRuntimeUnavailable(RunpodRuntimeError):
    pass


class RunpodRuntimeIntegrityError(RunpodRuntimeError):
    pass


@dataclass(frozen=True)
class RunpodInfrastructureStatus:
    available: bool
    execution_target_id: str | None = None
    gpu_identity: str | None = None
    runtime_identity: str | None = None


@dataclass(frozen=True)
class RunpodExecutionRequest:
    backend: str
    source_revision: str
    model_snapshots: Mapping[str, str]
    payload: Mapping[str, Any]
    output_media_kind: str


@dataclass(frozen=True)
class RunpodExecutionHandle:
    execution_id: str
    target_id: str


@dataclass(frozen=True)
class RunpodExecutionResult:
    execution_id: str
    target_id: str
    status: str
    backend: str
    source_revision: str
    model_snapshots: Mapping[str, str]
    gpu_identity: str
    runtime_identity: str
    artifact_ref: str
    seed: int | None = None
    generation_config: Mapping[str, Any] = field(default_factory=dict)
    elapsed_seconds: float | None = None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


class RunpodExecutionClient(Protocol):
    """Infrastructure-only transport. It never authorizes, routes, or publishes."""

    def probe(self) -> RunpodInfrastructureStatus: ...

    def submit(self, request: RunpodExecutionRequest) -> RunpodExecutionHandle: ...

    def wait(
        self,
        handle: RunpodExecutionHandle,
        *,
        timeout_seconds: int,
    ) -> RunpodExecutionResult: ...

    def materialize_artifact(
        self,
        handle: RunpodExecutionHandle,
        result: RunpodExecutionResult,
        *,
        destination_dir: Path,
    ) -> Path: ...


@dataclass(frozen=True)
class RunpodGenerativeRuntimeConfig:
    backend: str
    source_revision: str
    model_snapshots: Mapping[str, str]
    output_media_kind: str
    artifact_root: Path
    timeout_seconds: int = 7200


class RunpodGenerativeMediaRuntime:
    """Bounded Runpod adapter invoked only after Harness governance succeeds."""

    def __init__(
        self,
        config: RunpodGenerativeRuntimeConfig,
        *,
        client: RunpodExecutionClient,
    ) -> None:
        if not config.backend:
            raise ValueError("Runpod runtime backend is required")
        if not config.source_revision:
            raise ValueError("Runpod runtime source revision is required")
        if not config.model_snapshots:
            raise ValueError("Runpod runtime model snapshots are required")
        if config.output_media_kind not in {"video", "audio"}:
            raise ValueError("Unsupported Runpod output media kind")
        if config.timeout_seconds <= 0:
            raise ValueError("Runpod timeout must be positive")
        self._config = config
        self._client = client

    @property
    def backend(self) -> str:
        return self._config.backend

    def _validate_payload_boundary(self, payload: Mapping[str, Any]) -> None:
        forbidden = AUTHORITY_SHAPED_PAYLOAD_KEYS.intersection(payload)
        if forbidden:
            raise PermissionError(
                "Runpod runtime payload may not carry authority fields: "
                + ", ".join(sorted(forbidden))
            )

    def _validate_infrastructure(self) -> RunpodInfrastructureStatus:
        try:
            status = self._client.probe()
        except RunpodRuntimeError:
            raise
        except Exception as exc:
            raise RunpodRuntimeUnavailable(
                RunpodRuntimeFailureReason.RUNPOD_UNAVAILABLE,
                "Runpod infrastructure probe failed",
            ) from exc
        if not isinstance(status, RunpodInfrastructureStatus):
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.RUNPOD_RESULT_INVALID,
                "Runpod infrastructure probe returned an invalid result",
            )
        if not status.available:
            raise RunpodRuntimeUnavailable(
                RunpodRuntimeFailureReason.RUNPOD_UNAVAILABLE,
                "Runpod infrastructure is unavailable",
            )
        return status

    def _validate_remote_result(
        self,
        handle: RunpodExecutionHandle,
        result: RunpodExecutionResult,
    ) -> None:
        if result.execution_id != handle.execution_id or result.target_id != handle.target_id:
            raise RunpodRuntimeIntegrityError(
                RunpodRuntimeFailureReason.JOB_IDENTITY_MISMATCH,
                "Runpod result does not match submitted execution identity",
            )
        if result.status != "SUCCEEDED":
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.RUNPOD_EXECUTION_FAILED,
                "Runpod execution did not succeed",
            )
        if result.backend != self._config.backend:
            raise RunpodRuntimeIntegrityError(
                RunpodRuntimeFailureReason.BACKEND_IDENTITY_MISMATCH,
                "Runpod worker backend identity mismatch",
            )
        if result.source_revision != self._config.source_revision:
            raise RunpodRuntimeIntegrityError(
                RunpodRuntimeFailureReason.SOURCE_REVISION_MISMATCH,
                "Runpod worker source revision mismatch",
            )
        if dict(result.model_snapshots) != dict(self._config.model_snapshots):
            raise RunpodRuntimeIntegrityError(
                RunpodRuntimeFailureReason.MODEL_SNAPSHOT_MISMATCH,
                "Runpod worker model snapshot revisions mismatch",
            )
        if not isinstance(result.gpu_identity, str) or not result.gpu_identity.strip():
            raise RunpodRuntimeIntegrityError(
                RunpodRuntimeFailureReason.GPU_IDENTITY_MISSING,
                "Runpod worker GPU identity is missing",
            )
        if not isinstance(result.runtime_identity, str) or not result.runtime_identity.strip():
            raise RunpodRuntimeIntegrityError(
                RunpodRuntimeFailureReason.RUNTIME_IDENTITY_MISSING,
                "Runpod worker runtime identity is missing",
            )
        if not isinstance(result.artifact_ref, str) or not result.artifact_ref.strip():
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.ARTIFACT_UNAVAILABLE,
                "Runpod worker did not return an artifact reference",
            )

    def generate(self, payload: dict[str, Any]) -> GeneratedMediaRuntimeResult:
        if not isinstance(payload, dict):
            raise ValueError("Runpod runtime payload must be a mapping")
        self._validate_payload_boundary(payload)
        infrastructure = self._validate_infrastructure()

        request = RunpodExecutionRequest(
            backend=self._config.backend,
            source_revision=self._config.source_revision,
            model_snapshots=dict(self._config.model_snapshots),
            payload=dict(payload),
            output_media_kind=self._config.output_media_kind,
        )
        try:
            handle = self._client.submit(request)
        except RunpodRuntimeError:
            raise
        except Exception as exc:
            raise RunpodRuntimeUnavailable(
                RunpodRuntimeFailureReason.RUNPOD_UNAVAILABLE,
                "Runpod submission failed",
            ) from exc
        if not isinstance(handle, RunpodExecutionHandle):
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.RUNPOD_RESULT_INVALID,
                "Runpod submission returned an invalid execution handle",
            )
        if not handle.execution_id or not handle.target_id:
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.RUNPOD_RESULT_INVALID,
                "Runpod submission returned an incomplete execution handle",
            )

        try:
            result = self._client.wait(
                handle,
                timeout_seconds=self._config.timeout_seconds,
            )
        except RunpodRuntimeError:
            raise
        except Exception as exc:
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.RUNPOD_EXECUTION_FAILED,
                "Runpod execution transport failed",
            ) from exc
        if not isinstance(result, RunpodExecutionResult):
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.RUNPOD_RESULT_INVALID,
                "Runpod execution returned an invalid result",
            )
        self._validate_remote_result(handle, result)

        destination_dir = self._config.artifact_root / handle.execution_id
        try:
            path = self._client.materialize_artifact(
                handle,
                result,
                destination_dir=destination_dir,
            )
        except RunpodRuntimeError:
            raise
        except Exception as exc:
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.ARTIFACT_UNAVAILABLE,
                "Runpod artifact materialization failed",
            ) from exc
        if not isinstance(path, Path):
            path = Path(path)
        if not path.is_file() or path.stat().st_size <= 0:
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.ARTIFACT_UNAVAILABLE,
                "Runpod artifact was not materialized locally",
            )

        generation_config = dict(result.generation_config)
        generation_config["runpod"] = {
            "execution_id": handle.execution_id,
            "target_id": handle.target_id,
            "gpu_identity": result.gpu_identity,
            "runtime_identity": result.runtime_identity,
            "infrastructure_probe_target_id": infrastructure.execution_target_id,
            "source_revision": result.source_revision,
            "model_snapshots": dict(result.model_snapshots),
            "artifact_ref": result.artifact_ref,
        }

        return GeneratedMediaRuntimeResult(
            path=str(path),
            backend=result.backend,
            seed=result.seed,
            generation_config=generation_config,
            elapsed_seconds=result.elapsed_seconds,
            warnings=tuple(result.warnings),
        )


def create_hunyuan_runpod_runtime(
    repo_root: str | Path,
    *,
    client: RunpodExecutionClient,
) -> RunpodGenerativeMediaRuntime:
    root = Path(repo_root)
    return RunpodGenerativeMediaRuntime(
        RunpodGenerativeRuntimeConfig(
            backend="hunyuanvideo_i2v",
            source_revision="c8bba70b9517f08d770a9a2a3d1e93cc6d5b7949",
            model_snapshots={
                "tencent/HunyuanVideo-I2V": "3914f209367854b5e470f062c33159d5ab139e1e",
                "xtuner/llava-llama-3-8b-v1_1-transformers": "57be3132de24c7add61292c3bfbfc7c9d56f37ce",
                "openai/clip-vit-large-patch14": "e9c2a4fe1a4c98286816d3c7392c89c9c9b4865a",
            },
            output_media_kind="video",
            artifact_root=root / ".runtime" / "generative-media" / "runpod-artifacts",
        ),
        client=client,
    )


def create_ace_step_runpod_runtime(
    repo_root: str | Path,
    *,
    client: RunpodExecutionClient,
) -> RunpodGenerativeMediaRuntime:
    root = Path(repo_root)
    return RunpodGenerativeMediaRuntime(
        RunpodGenerativeRuntimeConfig(
            backend="ace_step",
            source_revision="dce621408bee8c31b4fcf4811682eb9359e1bc94",
            model_snapshots={
                "ACE-Step/Ace-Step1.5": "19671f406d603126926c1b7e2adc169acbcade22",
            },
            output_media_kind="audio",
            artifact_root=root / ".runtime" / "generative-media" / "runpod-artifacts",
        ),
        client=client,
    )
