from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import os
from pathlib import Path
import platform
import subprocess
from typing import Any, Callable, Mapping, Sequence

from app.services.generative_media_service import GeneratedMediaRuntimeResult


class RuntimeFailureReason(str, Enum):
    UNSUPPORTED_CONTROL_HOST = "UNSUPPORTED_CONTROL_HOST"
    UNSUPPORTED_HOST = "UNSUPPORTED_HOST"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SOURCE_REVISION_MISMATCH = "SOURCE_REVISION_MISMATCH"
    PYTHON_UNAVAILABLE = "PYTHON_UNAVAILABLE"
    PYTHON_VERSION_UNSUPPORTED = "PYTHON_VERSION_UNSUPPORTED"
    RUNNER_UNAVAILABLE = "RUNNER_UNAVAILABLE"
    MODEL_SNAPSHOT_MISSING = "MODEL_SNAPSHOT_MISSING"
    MODEL_SNAPSHOT_MISMATCH = "MODEL_SNAPSHOT_MISMATCH"
    NVIDIA_UNAVAILABLE = "NVIDIA_UNAVAILABLE"
    CUDA_UNAVAILABLE = "CUDA_UNAVAILABLE"
    SUBPROCESS_FAILED = "SUBPROCESS_FAILED"
    SUBPROCESS_TIMEOUT = "SUBPROCESS_TIMEOUT"
    INVALID_RESULT_JSON = "INVALID_RESULT_JSON"
    INVALID_RESULT = "INVALID_RESULT"
    BACKEND_IDENTITY_MISMATCH = "BACKEND_IDENTITY_MISMATCH"


class IsolatedRuntimeError(RuntimeError):
    """Base error for the bounded generative-media runtime boundary."""

    def __init__(self, reason: RuntimeFailureReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class IsolatedRuntimeUnavailable(IsolatedRuntimeError):
    """Runtime prerequisites or pinned assets are not available."""


class IsolatedRuntimeIntegrityError(IsolatedRuntimeError):
    """Pinned source/model provenance does not match the expected identity."""


@dataclass(frozen=True)
class RuntimeEnvironment:
    system: str
    machine: str
    is_termux: bool
    is_android: bool

    @property
    def is_control_host(self) -> bool:
        return self.is_termux or self.is_android


class RuntimeEnvironmentProbe:
    """Discover immutable host facts used by the runtime prerequisite boundary."""

    def probe(self) -> RuntimeEnvironment:
        return RuntimeEnvironment(
            system=platform.system(),
            machine=platform.machine(),
            is_termux=bool(os.environ.get("TERMUX_VERSION")),
            is_android=bool(os.environ.get("ANDROID_ROOT")),
        )


AUTHORITY_SHAPED_PAYLOAD_KEYS = frozenset(
    {
        "authorization_id",
        "harness_decision_id",
        "execution_id",
        "authorized_action",
        "capability_id",
        "provider_id",
        "model_id",
        "model_revision",
        "executor_binding",
        "fallback_provider",
        "fallback_model",
        "publish",
        "schedule",
    }
)

_SAFE_ENV_KEYS = (
    "PATH",
    "HOME",
    "LD_LIBRARY_PATH",
    "CUDA_HOME",
    "CUDA_PATH",
    "CUDA_VISIBLE_DEVICES",
    "HF_HOME",
    "XDG_CACHE_HOME",
    "TMPDIR",
)


@dataclass(frozen=True)
class SnapshotRequirement:
    repository: str
    revision: str
    marker_path: Path


@dataclass(frozen=True)
class IsolatedRuntimeConfig:
    backend: str
    source_dir: Path
    source_revision: str
    python_executable: Path
    runner_script: Path
    snapshot_requirements: tuple[SnapshotRequirement, ...]
    requires_nvidia: bool
    allowed_python_versions: tuple[str, ...] = ()
    timeout_seconds: int = 7200
    extra_env: Mapping[str, str] = field(default_factory=dict)


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _clean_subprocess_env(extra_env: Mapping[str, str]) -> dict[str, str]:
    env = {key: os.environ[key] for key in _SAFE_ENV_KEYS if key in os.environ}
    for key, value in extra_env.items():
        if not isinstance(key, str) or not key:
            raise ValueError("Runtime environment key must be a non-empty string")
        if not isinstance(value, str):
            raise ValueError("Runtime environment values must be strings")
        env[key] = value
    return env


def _git_head(
    source_dir: Path,
    *,
    command_runner: CommandRunner,
) -> str:
    try:
        completed = command_runner(
            ["git", "-C", str(source_dir), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise IsolatedRuntimeUnavailable(RuntimeFailureReason.SOURCE_UNAVAILABLE, "Unable to inspect runtime source revision") from exc
    return completed.stdout.strip()


def _read_snapshot_marker(requirement: SnapshotRequirement) -> str:
    try:
        value = requirement.marker_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise IsolatedRuntimeUnavailable(
            RuntimeFailureReason.MODEL_SNAPSHOT_MISSING,
            f"Missing model snapshot marker for {requirement.repository}",
        ) from exc
    if not value:
        raise IsolatedRuntimeIntegrityError(
            RuntimeFailureReason.MODEL_SNAPSHOT_MISMATCH,
            f"Empty model snapshot marker for {requirement.repository}",
        )
    return value


def _validate_nvidia(
    *,
    command_runner: CommandRunner,
) -> None:
    try:
        completed = command_runner(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise IsolatedRuntimeUnavailable(RuntimeFailureReason.NVIDIA_UNAVAILABLE, "NVIDIA GPU/CUDA runtime is unavailable") from exc
    if not completed.stdout.strip():
        raise IsolatedRuntimeUnavailable(RuntimeFailureReason.NVIDIA_UNAVAILABLE, "No NVIDIA GPU is visible to the runtime")


def _validate_python(
    python_executable: Path,
    allowed_versions: tuple[str, ...],
    *,
    command_runner: CommandRunner,
) -> None:
    if not allowed_versions:
        return
    try:
        completed = command_runner(
            [
                str(python_executable),
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise IsolatedRuntimeUnavailable(
            RuntimeFailureReason.PYTHON_UNAVAILABLE,
            "Unable to validate isolated Python runtime",
        ) from exc
    version = completed.stdout.strip()
    if version not in allowed_versions:
        raise IsolatedRuntimeUnavailable(
            RuntimeFailureReason.PYTHON_VERSION_UNSUPPORTED,
            f"Unsupported isolated Python version: {version}",
        )


def _validate_cuda(
    python_executable: Path,
    *,
    command_runner: CommandRunner,
) -> None:
    try:
        completed = command_runner(
            [
                str(python_executable),
                "-c",
                (
                    "import torch; "
                    "print((torch.version.cuda or '') + '|' + "
                    "str(torch.cuda.is_available()))"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise IsolatedRuntimeUnavailable(
            RuntimeFailureReason.CUDA_UNAVAILABLE,
            "Unable to validate isolated CUDA runtime",
        ) from exc
    value = completed.stdout.strip()
    if not value.endswith("|True") or value.startswith("|"):
        raise IsolatedRuntimeUnavailable(
            RuntimeFailureReason.CUDA_UNAVAILABLE,
            "CUDA is not available inside the isolated runtime",
        )


class IsolatedGenerativeMediaRuntime:
    """One-shot, private subprocess adapter used only after Harness governance."""

    def __init__(
        self,
        config: IsolatedRuntimeConfig,
        *,
        command_runner: CommandRunner = subprocess.run,
        environment_probe: RuntimeEnvironmentProbe | None = None,
    ) -> None:
        self._config = config
        self._command_runner = command_runner
        self._environment_probe = environment_probe or RuntimeEnvironmentProbe()

    @property
    def backend(self) -> str:
        return self._config.backend

    def _validate_payload_boundary(self, payload: Mapping[str, Any]) -> None:
        forbidden = AUTHORITY_SHAPED_PAYLOAD_KEYS.intersection(payload)
        if forbidden:
            raise PermissionError(
                "Runtime payload may not carry authority fields: "
                + ", ".join(sorted(forbidden))
            )

    def validate_installation(self) -> None:
        environment = self._environment_probe.probe()
        if environment.is_control_host:
            raise IsolatedRuntimeUnavailable(
                RuntimeFailureReason.UNSUPPORTED_CONTROL_HOST,
                "Termux/Android is a control host, not an ML executor",
            )
        if environment.system != "Linux":
            raise IsolatedRuntimeUnavailable(
                RuntimeFailureReason.UNSUPPORTED_HOST,
                "Isolated ML runtime requires Linux",
            )
        if not self._config.source_dir.is_dir():
            raise IsolatedRuntimeUnavailable(
                RuntimeFailureReason.SOURCE_UNAVAILABLE,
                "Pinned runtime source is unavailable",
            )
        if not self._config.python_executable.is_file():
            raise IsolatedRuntimeUnavailable(
                RuntimeFailureReason.PYTHON_UNAVAILABLE,
                "Isolated Python executable is unavailable",
            )
        if not self._config.runner_script.is_file():
            raise IsolatedRuntimeUnavailable(
                RuntimeFailureReason.RUNNER_UNAVAILABLE,
                "Bounded runtime runner is unavailable",
            )

        _validate_python(
            self._config.python_executable,
            self._config.allowed_python_versions,
            command_runner=self._command_runner,
        )

        actual_source_revision = _git_head(
            self._config.source_dir,
            command_runner=self._command_runner,
        )
        if actual_source_revision != self._config.source_revision:
            raise IsolatedRuntimeIntegrityError(RuntimeFailureReason.SOURCE_REVISION_MISMATCH, "Runtime source revision mismatch")

        for requirement in self._config.snapshot_requirements:
            actual_revision = _read_snapshot_marker(requirement)
            if actual_revision != requirement.revision:
                raise IsolatedRuntimeIntegrityError(
                    RuntimeFailureReason.MODEL_SNAPSHOT_MISMATCH,
                    f"Model snapshot mismatch for {requirement.repository}",
                )

        if self._config.requires_nvidia:
            _validate_nvidia(command_runner=self._command_runner)
            _validate_cuda(
                self._config.python_executable,
                command_runner=self._command_runner,
            )

    def generate(self, payload: dict[str, Any]) -> GeneratedMediaRuntimeResult:
        if not isinstance(payload, dict):
            raise ValueError("Runtime payload must be a mapping")
        self._validate_payload_boundary(payload)
        self.validate_installation()

        env = _clean_subprocess_env(self._config.extra_env)
        request = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        try:
            completed = self._command_runner(
                [
                    str(self._config.python_executable),
                    str(self._config.runner_script),
                ],
                input=request,
                check=True,
                capture_output=True,
                text=True,
                timeout=self._config.timeout_seconds,
                cwd=str(self._config.source_dir),
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise IsolatedRuntimeError(RuntimeFailureReason.SUBPROCESS_TIMEOUT, "Generative runtime timed out") from exc
        except subprocess.CalledProcessError as exc:
            raise IsolatedRuntimeError(RuntimeFailureReason.SUBPROCESS_FAILED, "Generative runtime subprocess failed") from exc
        except FileNotFoundError as exc:
            raise IsolatedRuntimeUnavailable(RuntimeFailureReason.RUNNER_UNAVAILABLE, "Generative runtime executable is missing") from exc

        stdout = completed.stdout.strip()
        if not stdout:
            raise IsolatedRuntimeError(RuntimeFailureReason.INVALID_RESULT, "Generative runtime returned no result")

        try:
            response = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise IsolatedRuntimeError(RuntimeFailureReason.INVALID_RESULT_JSON, "Generative runtime returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise IsolatedRuntimeError(RuntimeFailureReason.INVALID_RESULT, "Generative runtime result must be an object")

        path = response.get("path")
        backend = response.get("backend")
        if not isinstance(path, str) or not path.strip():
            raise IsolatedRuntimeError(RuntimeFailureReason.INVALID_RESULT, "Generative runtime did not return an artifact path")
        if backend != self._config.backend:
            raise IsolatedRuntimeIntegrityError(RuntimeFailureReason.BACKEND_IDENTITY_MISMATCH, "Generative runtime backend identity mismatch")

        warnings = response.get("warnings") or []
        if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
            raise IsolatedRuntimeError(RuntimeFailureReason.INVALID_RESULT, "Generative runtime warnings must be strings")

        generation_config = response.get("generation_config") or {}
        if not isinstance(generation_config, dict):
            raise IsolatedRuntimeError(RuntimeFailureReason.INVALID_RESULT, "Generative runtime generation_config must be an object")

        seed = response.get("seed")
        if seed is not None and not isinstance(seed, int):
            raise IsolatedRuntimeError(RuntimeFailureReason.INVALID_RESULT, "Generative runtime seed must be an integer")

        elapsed_seconds = response.get("elapsed_seconds")
        if elapsed_seconds is not None:
            if not isinstance(elapsed_seconds, (int, float)) or elapsed_seconds < 0:
                raise IsolatedRuntimeError(
                    RuntimeFailureReason.INVALID_RESULT,
                    "Generative runtime elapsed_seconds must be non-negative",
                )

        return GeneratedMediaRuntimeResult(
            path=path,
            backend=backend,
            seed=seed,
            generation_config=dict(generation_config),
            elapsed_seconds=(
                float(elapsed_seconds) if elapsed_seconds is not None else None
            ),
            warnings=tuple(warnings),
        )


def create_hunyuan_isolated_runtime(
    repo_root: str | Path,
    *,
    command_runner: CommandRunner = subprocess.run,
    environment_probe: RuntimeEnvironmentProbe | None = None,
) -> IsolatedGenerativeMediaRuntime:
    root = Path(repo_root)
    runtime_root = root / ".runtime" / "generative-media" / "hunyuanvideo-i2v"
    models = runtime_root / "models"
    return IsolatedGenerativeMediaRuntime(
        IsolatedRuntimeConfig(
            backend="hunyuanvideo_i2v",
            source_dir=runtime_root / "src",
            source_revision="c8bba70b9517f08d770a9a2a3d1e93cc6d5b7949",
            python_executable=runtime_root / "venv" / "bin" / "python",
            runner_script=root
            / "infra"
            / "generative-media"
            / "runners"
            / "hunyuan_once.py",
            snapshot_requirements=(
                SnapshotRequirement(
                    repository="tencent/HunyuanVideo-I2V",
                    revision="3914f209367854b5e470f062c33159d5ab139e1e",
                    marker_path=models / "hunyuanvideo-i2v.snapshot",
                ),
                SnapshotRequirement(
                    repository="xtuner/llava-llama-3-8b-v1_1-transformers",
                    revision="57be3132de24c7add61292c3bfbfc7c9d56f37ce",
                    marker_path=models / "llava.snapshot",
                ),
                SnapshotRequirement(
                    repository="openai/clip-vit-large-patch14",
                    revision="e9c2a4fe1a4c98286816d3c7392c89c9c9b4865a",
                    marker_path=models / "clip.snapshot",
                ),
            ),
            requires_nvidia=True,
            allowed_python_versions=("3.11",),
            extra_env={
                "BR_HUNYUAN_MODEL_DIR": str(models / "ckpts"),
                "BR_GENERATIVE_OUTPUT_DIR": str(runtime_root / "output"),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
            },
        ),
        command_runner=command_runner,
        environment_probe=environment_probe,
    )


def create_ace_step_isolated_runtime(
    repo_root: str | Path,
    *,
    command_runner: CommandRunner = subprocess.run,
    environment_probe: RuntimeEnvironmentProbe | None = None,
) -> IsolatedGenerativeMediaRuntime:
    root = Path(repo_root)
    runtime_root = root / ".runtime" / "generative-media" / "ace-step"
    models = runtime_root / "models"
    return IsolatedGenerativeMediaRuntime(
        IsolatedRuntimeConfig(
            backend="ace_step",
            source_dir=runtime_root / "src",
            source_revision="dce621408bee8c31b4fcf4811682eb9359e1bc94",
            python_executable=runtime_root / "src" / ".venv" / "bin" / "python",
            runner_script=root
            / "infra"
            / "generative-media"
            / "runners"
            / "ace_step_once.py",
            snapshot_requirements=(
                SnapshotRequirement(
                    repository="ACE-Step/Ace-Step1.5",
                    revision="19671f406d603126926c1b7e2adc169acbcade22",
                    marker_path=models / "ace-step.snapshot",
                ),
            ),
            requires_nvidia=False,
            allowed_python_versions=("3.11", "3.12"),
            extra_env={
                "ACESTEP_CHECKPOINTS_DIR": str(models / "checkpoint"),
                "BR_GENERATIVE_OUTPUT_DIR": str(runtime_root / "output"),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
            },
        ),
        command_runner=command_runner,
        environment_probe=environment_probe,
    )
