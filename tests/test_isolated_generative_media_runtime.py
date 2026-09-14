from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from app.services.isolated_generative_media_runtime import (
    IsolatedGenerativeMediaRuntime,
    IsolatedRuntimeConfig,
    IsolatedRuntimeError,
    IsolatedRuntimeIntegrityError,
    IsolatedRuntimeUnavailable,
    RuntimeEnvironment,
    RuntimeEnvironmentProbe,
    RuntimeFailureReason,
    SnapshotRequirement,
)


class StaticEnvironmentProbe(RuntimeEnvironmentProbe):
    def __init__(
        self,
        *,
        system="Linux",
        machine="x86_64",
        is_termux=False,
        is_android=False,
    ):
        self.environment = RuntimeEnvironment(
            system=system,
            machine=machine,
            is_termux=is_termux,
            is_android=is_android,
        )

    def probe(self):
        return self.environment


class FakeRunner:
    def __init__(self, *, source_revision="source-pin", gpu_output="GPU, 81920 MiB"):
        self.source_revision = source_revision
        self.gpu_output = gpu_output
        self.calls = []
        self.runtime_stdout = json.dumps(
            {
                "path": "/tmp/output.mp4",
                "backend": "test_backend",
                "seed": 7,
                "generation_config": {"steps": 8},
                "elapsed_seconds": 1.5,
                "warnings": [],
            }
        )

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), dict(kwargs)))
        if command[0] == "git":
            return subprocess.CompletedProcess(command, 0, self.source_revision, "")
        if command[0] == "nvidia-smi":
            return subprocess.CompletedProcess(command, 0, self.gpu_output, "")
        if "-c" in command:
            code = command[command.index("-c") + 1]
            if "sys.version_info" in code:
                return subprocess.CompletedProcess(command, 0, "3.11\n", "")
            if "torch.cuda.is_available" in code:
                return subprocess.CompletedProcess(command, 0, "12.4|True\n", "")
        return subprocess.CompletedProcess(command, 0, self.runtime_stdout, "")


def _runtime(tmp_path: Path, *, requires_nvidia=False, runner=None, environment_probe=None):
    source = tmp_path / "src"
    source.mkdir()
    python = tmp_path / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    runner_script = tmp_path / "runner.py"
    runner_script.write_text("", encoding="utf-8")
    marker = tmp_path / "model.snapshot"
    marker.write_text("model-pin\n", encoding="utf-8")
    fake = runner or FakeRunner()
    config = IsolatedRuntimeConfig(
        backend="test_backend",
        source_dir=source,
        source_revision="source-pin",
        python_executable=python,
        runner_script=runner_script,
        snapshot_requirements=(
            SnapshotRequirement("org/model", "model-pin", marker),
        ),
        requires_nvidia=requires_nvidia,
        allowed_python_versions=("3.11",),
        timeout_seconds=10,
    )
    return IsolatedGenerativeMediaRuntime(
        config,
        command_runner=fake,
        environment_probe=environment_probe or StaticEnvironmentProbe(),
    ), fake, marker


def test_unsupported_host_fails_closed(tmp_path):
    runtime, fake, _ = _runtime(
        tmp_path,
        environment_probe=StaticEnvironmentProbe(system="Darwin", machine="arm64"),
    )
    with pytest.raises(IsolatedRuntimeUnavailable) as exc_info:
        runtime.validate_installation()
    assert exc_info.value.reason is RuntimeFailureReason.UNSUPPORTED_HOST
    assert not fake.calls


def test_source_revision_mismatch_fails_closed(tmp_path):
    runtime, _, _ = _runtime(
        tmp_path,
        runner=FakeRunner(source_revision="wrong"),
    )
    with pytest.raises(IsolatedRuntimeIntegrityError) as exc_info:
        runtime.validate_installation()
    assert exc_info.value.reason is RuntimeFailureReason.SOURCE_REVISION_MISMATCH


def test_model_snapshot_mismatch_fails_closed(tmp_path):
    runtime, _, marker = _runtime(tmp_path)
    marker.write_text("wrong\n", encoding="utf-8")
    with pytest.raises(IsolatedRuntimeIntegrityError) as exc_info:
        runtime.validate_installation()
    assert exc_info.value.reason is RuntimeFailureReason.MODEL_SNAPSHOT_MISMATCH


def test_missing_model_snapshot_fails_closed(tmp_path):
    runtime, _, marker = _runtime(tmp_path)
    marker.unlink()
    with pytest.raises(IsolatedRuntimeUnavailable) as exc_info:
        runtime.validate_installation()
    assert exc_info.value.reason is RuntimeFailureReason.MODEL_SNAPSHOT_MISSING


def test_missing_gpu_fails_closed(tmp_path):
    class MissingGPU(FakeRunner):
        def __call__(self, command, **kwargs):
            if command[0] == "nvidia-smi":
                raise FileNotFoundError
            return super().__call__(command, **kwargs)

    runtime, _, _ = _runtime(
        tmp_path,
        requires_nvidia=True,
        runner=MissingGPU(),
    )
    with pytest.raises(IsolatedRuntimeUnavailable) as exc_info:
        runtime.validate_installation()
    assert exc_info.value.reason is RuntimeFailureReason.NVIDIA_UNAVAILABLE


def test_termux_control_host_fails_closed(tmp_path):
    runtime, fake, _ = _runtime(
        tmp_path,
        environment_probe=StaticEnvironmentProbe(is_termux=True),
    )
    with pytest.raises(IsolatedRuntimeUnavailable) as exc_info:
        runtime.validate_installation()
    assert exc_info.value.reason is RuntimeFailureReason.UNSUPPORTED_CONTROL_HOST
    assert not fake.calls


def test_real_environment_probe_reads_termux_fail_closed(tmp_path, monkeypatch):
    runtime, fake, _ = _runtime(
        tmp_path,
        environment_probe=RuntimeEnvironmentProbe(),
    )
    monkeypatch.setenv("TERMUX_VERSION", "0.118")
    monkeypatch.delenv("ANDROID_ROOT", raising=False)
    with pytest.raises(IsolatedRuntimeUnavailable) as exc_info:
        runtime.validate_installation()
    assert exc_info.value.reason is RuntimeFailureReason.UNSUPPORTED_CONTROL_HOST
    assert not fake.calls


def test_wrong_python_version_fails_closed(tmp_path):
    class Python312(FakeRunner):
        def __call__(self, command, **kwargs):
            if "-c" in command and "sys.version_info" in command[command.index("-c") + 1]:
                self.calls.append((list(command), dict(kwargs)))
                return subprocess.CompletedProcess(command, 0, "3.12\n", "")
            return super().__call__(command, **kwargs)

    runtime, _, _ = _runtime(tmp_path, runner=Python312())
    with pytest.raises(IsolatedRuntimeUnavailable) as exc_info:
        runtime.validate_installation()
    assert exc_info.value.reason is RuntimeFailureReason.PYTHON_VERSION_UNSUPPORTED


def test_cuda_unavailable_inside_venv_fails_closed(tmp_path):
    class NoCudaInTorch(FakeRunner):
        def __call__(self, command, **kwargs):
            if "-c" in command and "torch.cuda.is_available" in command[command.index("-c") + 1]:
                self.calls.append((list(command), dict(kwargs)))
                return subprocess.CompletedProcess(command, 0, "12.4|False\n", "")
            return super().__call__(command, **kwargs)

    runtime, _, _ = _runtime(
        tmp_path,
        requires_nvidia=True,
        runner=NoCudaInTorch(),
    )
    with pytest.raises(IsolatedRuntimeUnavailable) as exc_info:
        runtime.validate_installation()
    assert exc_info.value.reason is RuntimeFailureReason.CUDA_UNAVAILABLE


@pytest.mark.parametrize(
    "field",
    [
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
    ],
)
def test_authority_shaped_payload_fields_are_rejected(tmp_path, field):
    runtime, fake, _ = _runtime(tmp_path)
    with pytest.raises(PermissionError, match="authority fields"):
        runtime.generate({"prompt": "x", field: "forged"})
    assert not fake.calls


def test_subprocess_failure_has_no_fallback(tmp_path):
    class FailingRunner(FakeRunner):
        def __call__(self, command, **kwargs):
            if command[0] in {"git", "nvidia-smi"} or "-c" in command:
                return super().__call__(command, **kwargs)
            self.calls.append((list(command), dict(kwargs)))
            raise subprocess.CalledProcessError(1, command)

    runtime, fake, _ = _runtime(tmp_path, runner=FailingRunner())
    with pytest.raises(IsolatedRuntimeError) as exc_info:
        runtime.generate({"prompt": "x"})
    assert exc_info.value.reason is RuntimeFailureReason.SUBPROCESS_FAILED
    generation_calls = [
        call
        for call in fake.calls
        if call[0][0] not in {"git", "nvidia-smi"}
        and "-c" not in call[0]
    ]
    assert len(generation_calls) == 1


def test_valid_runtime_result_is_bounded_evidence_input(tmp_path):
    runtime, fake, _ = _runtime(tmp_path)
    result = runtime.generate({"prompt": "x", "seed": 7})
    assert result.path == "/tmp/output.mp4"
    assert result.backend == "test_backend"
    assert result.seed == 7
    assert result.generation_config == {"steps": 8}
    assert result.elapsed_seconds == 1.5
    runtime_call = fake.calls[-1]
    assert runtime_call[0][0].endswith("/python")
    submitted = json.loads(runtime_call[1]["input"])
    assert submitted == {"prompt": "x", "seed": 7}


def test_backend_identity_mismatch_is_rejected(tmp_path):
    fake = FakeRunner()
    fake.runtime_stdout = json.dumps(
        {"path": "/tmp/x", "backend": "other", "warnings": []}
    )
    runtime, _, _ = _runtime(tmp_path, runner=fake)
    with pytest.raises(IsolatedRuntimeIntegrityError) as exc_info:
        runtime.generate({"prompt": "x"})
    assert exc_info.value.reason is RuntimeFailureReason.BACKEND_IDENTITY_MISMATCH


def test_invalid_json_result_is_rejected(tmp_path):
    fake = FakeRunner()
    fake.runtime_stdout = "not-json"
    runtime, _, _ = _runtime(tmp_path, runner=fake)
    with pytest.raises(IsolatedRuntimeError) as exc_info:
        runtime.generate({"prompt": "x"})
    assert exc_info.value.reason is RuntimeFailureReason.INVALID_RESULT_JSON


def test_runtime_exposes_no_authority_publication_or_scheduler_surface(tmp_path):
    runtime, _, _ = _runtime(tmp_path)
    for name in (
        "authorize",
        "issue_authorization",
        "route",
        "select_provider",
        "select_model",
        "select_executor",
        "publish",
        "schedule",
        "fallback",
    ):
        assert not hasattr(runtime, name)


def test_subprocess_environment_is_allowlisted(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "must-not-leak")
    monkeypatch.setenv("PATH", "/usr/bin")
    runtime, fake, _ = _runtime(tmp_path)
    runtime.generate({"prompt": "x"})
    env = fake.calls[-1][1]["env"]
    assert env["PATH"] == "/usr/bin"
    assert "SECRET_TOKEN" not in env
