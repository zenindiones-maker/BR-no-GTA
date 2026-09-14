from __future__ import annotations

from pathlib import Path

import pytest

from app.services.runpod_generative_runtime import (
    RunpodExecutionHandle,
    RunpodExecutionRequest,
    RunpodExecutionResult,
    RunpodGenerativeMediaRuntime,
    RunpodGenerativeRuntimeConfig,
    RunpodInfrastructureStatus,
    RunpodRuntimeError,
    RunpodRuntimeFailureReason,
    RunpodRuntimeIntegrityError,
    RunpodRuntimeUnavailable,
    create_ace_step_runpod_runtime,
    create_hunyuan_runpod_runtime,
)


class FakeRunpodClient:
    def __init__(self, artifact_path: Path):
        self.artifact_path = artifact_path
        self.probe_result = RunpodInfrastructureStatus(
            available=True,
            execution_target_id="pod-test",
            gpu_identity="NVIDIA A100 80GB",
            runtime_identity="linux-x86_64-cuda12.4",
        )
        self.handle = RunpodExecutionHandle("job-1", "pod-test")
        self.result = RunpodExecutionResult(
            execution_id="job-1",
            target_id="pod-test",
            status="SUCCEEDED",
            backend="test_backend",
            source_revision="source-pin",
            model_snapshots={"org/model": "model-pin"},
            gpu_identity="NVIDIA A100 80GB",
            runtime_identity="linux-x86_64-cuda12.4",
            artifact_ref="remote://artifact-1",
            seed=7,
            generation_config={"steps": 8},
            elapsed_seconds=1.5,
            warnings=("test-warning",),
        )
        self.requests = []
        self.waits = []
        self.materializations = []

    def probe(self):
        return self.probe_result

    def submit(self, request):
        self.requests.append(request)
        return self.handle

    def wait(self, handle, *, timeout_seconds):
        self.waits.append((handle, timeout_seconds))
        return self.result

    def materialize_artifact(self, handle, result, *, destination_dir):
        self.materializations.append((handle, result, destination_dir))
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / self.artifact_path.name
        destination.write_bytes(self.artifact_path.read_bytes())
        return destination


def _runtime(tmp_path: Path, client: FakeRunpodClient):
    return RunpodGenerativeMediaRuntime(
        RunpodGenerativeRuntimeConfig(
            backend="test_backend",
            source_revision="source-pin",
            model_snapshots={"org/model": "model-pin"},
            output_media_kind="video",
            artifact_root=tmp_path / "artifacts",
            timeout_seconds=15,
        ),
        client=client,
    )


def _artifact(tmp_path: Path):
    path = tmp_path / "remote.mp4"
    path.write_bytes(b"bounded-runpod-artifact")
    return path


def test_runpod_unavailable_fails_closed(tmp_path):
    client = FakeRunpodClient(_artifact(tmp_path))
    client.probe_result = RunpodInfrastructureStatus(available=False)
    runtime = _runtime(tmp_path, client)
    with pytest.raises(RunpodRuntimeUnavailable) as exc_info:
        runtime.generate({"prompt": "x"})
    assert exc_info.value.reason is RunpodRuntimeFailureReason.RUNPOD_UNAVAILABLE
    assert client.requests == []


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
def test_authority_shaped_fields_never_reach_runpod(tmp_path, field):
    client = FakeRunpodClient(_artifact(tmp_path))
    runtime = _runtime(tmp_path, client)
    with pytest.raises(PermissionError):
        runtime.generate({"prompt": "x", field: "forged"})
    assert client.requests == []


def test_submitted_request_contains_only_runtime_contract(tmp_path):
    client = FakeRunpodClient(_artifact(tmp_path))
    runtime = _runtime(tmp_path, client)
    runtime.generate({"prompt": "x", "seed": 7})
    request = client.requests[0]
    assert isinstance(request, RunpodExecutionRequest)
    assert request.backend == "test_backend"
    assert request.source_revision == "source-pin"
    assert dict(request.model_snapshots) == {"org/model": "model-pin"}
    assert dict(request.payload) == {"prompt": "x", "seed": 7}


def test_remote_execution_failure_has_no_fallback(tmp_path):
    client = FakeRunpodClient(_artifact(tmp_path))
    client.result = RunpodExecutionResult(
        **{**client.result.__dict__, "status": "FAILED", "errors": ("boom",)}
    )
    runtime = _runtime(tmp_path, client)
    with pytest.raises(RunpodRuntimeError) as exc_info:
        runtime.generate({"prompt": "x"})
    assert exc_info.value.reason is RunpodRuntimeFailureReason.RUNPOD_EXECUTION_FAILED
    assert len(client.requests) == 1
    assert client.materializations == []


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("backend", "other", RunpodRuntimeFailureReason.BACKEND_IDENTITY_MISMATCH),
        ("source_revision", "wrong", RunpodRuntimeFailureReason.SOURCE_REVISION_MISMATCH),
        ("model_snapshots", {"org/model": "wrong"}, RunpodRuntimeFailureReason.MODEL_SNAPSHOT_MISMATCH),
        ("gpu_identity", "", RunpodRuntimeFailureReason.GPU_IDENTITY_MISSING),
        ("runtime_identity", "", RunpodRuntimeFailureReason.RUNTIME_IDENTITY_MISSING),
    ],
)
def test_remote_identity_mismatch_fails_closed(tmp_path, field, value, reason):
    client = FakeRunpodClient(_artifact(tmp_path))
    client.result = RunpodExecutionResult(
        **{**client.result.__dict__, field: value}
    )
    runtime = _runtime(tmp_path, client)
    with pytest.raises(RunpodRuntimeIntegrityError) as exc_info:
        runtime.generate({"prompt": "x"})
    assert exc_info.value.reason is reason
    assert client.materializations == []


def test_job_identity_mismatch_fails_closed(tmp_path):
    client = FakeRunpodClient(_artifact(tmp_path))
    client.result = RunpodExecutionResult(
        **{**client.result.__dict__, "execution_id": "other-job"}
    )
    runtime = _runtime(tmp_path, client)
    with pytest.raises(RunpodRuntimeIntegrityError) as exc_info:
        runtime.generate({"prompt": "x"})
    assert exc_info.value.reason is RunpodRuntimeFailureReason.JOB_IDENTITY_MISMATCH


def test_missing_materialized_artifact_fails_closed(tmp_path):
    class MissingArtifactClient(FakeRunpodClient):
        def materialize_artifact(self, handle, result, *, destination_dir):
            return destination_dir / "missing.mp4"

    client = MissingArtifactClient(_artifact(tmp_path))
    runtime = _runtime(tmp_path, client)
    with pytest.raises(RunpodRuntimeError) as exc_info:
        runtime.generate({"prompt": "x"})
    assert exc_info.value.reason is RunpodRuntimeFailureReason.ARTIFACT_UNAVAILABLE


def test_valid_result_is_materialized_for_existing_artifact_validator(tmp_path):
    client = FakeRunpodClient(_artifact(tmp_path))
    runtime = _runtime(tmp_path, client)
    result = runtime.generate({"prompt": "x", "seed": 7})
    assert Path(result.path).is_file()
    assert result.backend == "test_backend"
    assert result.seed == 7
    assert result.elapsed_seconds == 1.5
    assert result.warnings == ("test-warning",)
    runpod = result.generation_config["runpod"]
    assert runpod["execution_id"] == "job-1"
    assert runpod["target_id"] == "pod-test"
    assert runpod["gpu_identity"] == "NVIDIA A100 80GB"
    assert runpod["runtime_identity"] == "linux-x86_64-cuda12.4"
    assert runpod["source_revision"] == "source-pin"
    assert runpod["model_snapshots"] == {"org/model": "model-pin"}
    assert runpod["artifact_ref"] == "remote://artifact-1"


def test_runtime_exposes_no_authority_publication_scheduler_or_fallback_surface(tmp_path):
    client = FakeRunpodClient(_artifact(tmp_path))
    runtime = _runtime(tmp_path, client)
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


def test_hunyuan_factory_preserves_exact_pins(tmp_path):
    client = FakeRunpodClient(_artifact(tmp_path))
    runtime = create_hunyuan_runpod_runtime(tmp_path, client=client)
    config = runtime._config
    assert config.backend == "hunyuanvideo_i2v"
    assert config.source_revision == "c8bba70b9517f08d770a9a2a3d1e93cc6d5b7949"
    assert config.model_snapshots["tencent/HunyuanVideo-I2V"] == "3914f209367854b5e470f062c33159d5ab139e1e"
    assert config.model_snapshots["xtuner/llava-llama-3-8b-v1_1-transformers"] == "57be3132de24c7add61292c3bfbfc7c9d56f37ce"
    assert config.model_snapshots["openai/clip-vit-large-patch14"] == "e9c2a4fe1a4c98286816d3c7392c89c9c9b4865a"


def test_ace_step_factory_preserves_exact_pins(tmp_path):
    client = FakeRunpodClient(_artifact(tmp_path))
    runtime = create_ace_step_runpod_runtime(tmp_path, client=client)
    config = runtime._config
    assert config.backend == "ace_step"
    assert config.source_revision == "dce621408bee8c31b4fcf4811682eb9359e1bc94"
    assert config.model_snapshots == {
        "ACE-Step/Ace-Step1.5": "19671f406d603126926c1b7e2adc169acbcade22"
    }
