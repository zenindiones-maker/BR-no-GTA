from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import subprocess
import types
import urllib.request

import pytest

from app.services.runpod_http_execution_client import RunpodHttpExecutionClient
from app.services.runpod_generative_runtime import (
    RunpodExecutionRequest,
    RunpodRuntimeError,
    RunpodRuntimeFailureReason,
)


class FakeResponse:
    def __init__(self, payload, *, raw=False):
        self._payload = payload
        self._raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        if self._raw:
            return self._payload
        return json.dumps(self._payload).encode()


class FakeUrlOpen:
    def __init__(self):
        self.calls = []
        self.execution_status = "SUCCEEDED"

    def __call__(self, request, timeout=None):
        self.calls.append((request, timeout))
        path = request.full_url
        assert request.headers.get("Authorization") == "Bearer smoke-token"
        if path.endswith("/health"):
            return FakeResponse({
                "status": "READY",
                "gpu_identity": "NVIDIA RTX 4090, 24564 MiB, 550.1",
                "runtime_identity": "Linux-x86_64-python3.11",
            })
        if path.endswith("/execute"):
            submitted = json.loads(request.data.decode())
            assert submitted["backend"] == "runpod_infra_smoke"
            return FakeResponse({"execution_id": "exec-1"})
        if path.endswith("/executions/exec-1"):
            return FakeResponse({
                "execution_id": "exec-1",
                "status": self.execution_status,
                "backend": "runpod_infra_smoke",
                "source_revision": "source-pin",
                "model_snapshots": {"org/model": "model-pin"},
                "gpu_identity": "NVIDIA RTX 4090, 24564 MiB, 550.1",
                "runtime_identity": "Linux-x86_64-python3.11",
                "artifact_ref": "/tmp/infra-smoke.wav",
                "generation_config": {
                    "artifact_class": "INFRA_SMOKE_ARTIFACT",
                    "synthetic": True,
                },
                "warnings": ["synthetic"],
                "errors": [],
                "elapsed_seconds": 0.1,
            })
        if path.endswith("/artifacts/exec-1"):
            return FakeResponse(b"RIFFsynthetic", raw=True)
        raise AssertionError(path)


def _client(fake):
    return RunpodHttpExecutionClient(
        pod_id="pod-123",
        bearer_token="smoke-token",
        urlopen=fake,
        poll_interval_seconds=0.001,
    )


def test_http_client_probe_submit_wait_and_materialize(tmp_path):
    fake = FakeUrlOpen()
    client = _client(fake)
    status = client.probe()
    assert status.available is True
    assert status.execution_target_id == "pod-123"

    handle = client.submit(RunpodExecutionRequest(
        backend="runpod_infra_smoke",
        source_revision="source-pin",
        model_snapshots={"org/model": "model-pin"},
        payload={"target_backend": "ace_step"},
        output_media_kind="audio",
    ))
    assert handle.execution_id == "exec-1"
    assert handle.target_id == "pod-123"

    result = client.wait(handle, timeout_seconds=2)
    assert result.status == "SUCCEEDED"
    assert result.backend == "runpod_infra_smoke"
    assert result.gpu_identity.startswith("NVIDIA")

    artifact = client.materialize_artifact(
        handle,
        result,
        destination_dir=tmp_path,
    )
    assert artifact.read_bytes() == b"RIFFsynthetic"


def test_http_client_requires_ephemeral_bearer():
    with pytest.raises(ValueError, match="bearer"):
        RunpodHttpExecutionClient(pod_id="p", bearer_token="")


def test_http_client_invalid_json_fails_closed():
    class Invalid:
        def __call__(self, request, timeout=None):
            return FakeResponse(b"not-json", raw=True)
    with pytest.raises(RunpodRuntimeError) as exc:
        RunpodHttpExecutionClient(
            pod_id="p", bearer_token="t", urlopen=Invalid()
        ).probe()
    assert exc.value.reason is RunpodRuntimeFailureReason.RUNPOD_RESULT_INVALID


def _load_worker():
    path = Path(__file__).parents[1] / "infra/generative-media/runpod/worker_once.py"
    spec = importlib.util.spec_from_file_location("worker_once_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_infra_smoke_is_explicit_and_does_not_load_models(tmp_path, monkeypatch):
    worker = _load_worker()
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        assert command[0] == "nvidia-smi"
        return subprocess.CompletedProcess(command, 0, "NVIDIA RTX 4090, 24564 MiB, 550.1\n", "")

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    request = {
        "backend": "runpod_infra_smoke",
        "source_revision": worker.ACE_STEP_SOURCE_REVISION,
        "model_snapshots": dict(worker.ACE_STEP_MODEL_SNAPSHOTS),
        "payload": {
            "target_backend": "ace_step",
            "output_dir": str(tmp_path),
        },
        "output_media_kind": "audio",
    }
    result = worker.execute_worker_request(request)
    assert result["backend"] == "runpod_infra_smoke"
    assert result["target_backend"] == "ace_step"
    assert result["generation_config"]["artifact_class"] == "INFRA_SMOKE_ARTIFACT"
    assert result["generation_config"]["synthetic"] is True
    assert Path(result["artifact_ref"]).is_file()
    assert calls == [[
        "nvidia-smi",
        "--query-gpu=name,memory.total,driver_version",
        "--format=csv,noheader",
    ]]


def test_worker_infra_smoke_rejects_snapshot_drift(tmp_path, monkeypatch):
    worker = _load_worker()
    monkeypatch.setattr(worker, "_gpu_identity", lambda: "GPU")
    request = {
        "backend": "runpod_infra_smoke",
        "source_revision": worker.ACE_STEP_SOURCE_REVISION,
        "model_snapshots": {"ACE-Step/Ace-Step1.5": "wrong"},
        "payload": {"target_backend": "ace_step", "output_dir": str(tmp_path)},
    }
    with pytest.raises(PermissionError, match="snapshot"):
        worker.execute_worker_request(request)


def test_worker_infra_smoke_rejects_source_drift(tmp_path, monkeypatch):
    worker = _load_worker()
    monkeypatch.setattr(worker, "_gpu_identity", lambda: "GPU")
    request = {
        "backend": "runpod_infra_smoke",
        "source_revision": "wrong",
        "model_snapshots": dict(worker.HUNYUAN_MODEL_SNAPSHOTS),
        "payload": {"target_backend": "hunyuanvideo_i2v", "output_dir": str(tmp_path)},
    }
    with pytest.raises(PermissionError, match="source revision"):
        worker.execute_worker_request(request)


def test_worker_probe_only_requires_gpu(monkeypatch):
    worker = _load_worker()
    monkeypatch.setattr(worker, "_gpu_identity", lambda: "GPU-X")
    result = worker.execute_worker_request({
        "backend": "runpod_infra_smoke",
        "probe_only": True,
    })
    assert result["backend"] == "runpod_infra_smoke"
    assert result["gpu_identity"] == "GPU-X"
