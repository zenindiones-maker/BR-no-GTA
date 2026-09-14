from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path
import time
import wave

HUNYUAN_SOURCE_REVISION = "c8bba70b9517f08d770a9a2a3d1e93cc6d5b7949"
HUNYUAN_MODEL_SNAPSHOTS = {
    "tencent/HunyuanVideo-I2V": "3914f209367854b5e470f062c33159d5ab139e1e",
    "xtuner/llava-llama-3-8b-v1_1-transformers": "57be3132de24c7add61292c3bfbfc7c9d56f37ce",
    "openai/clip-vit-large-patch14": "e9c2a4fe1a4c98286816d3c7392c89c9c9b4865a",
}
ACE_STEP_SOURCE_REVISION = "dce621408bee8c31b4fcf4811682eb9359e1bc94"
ACE_STEP_MODEL_SNAPSHOTS = {
    "ACE-Step/Ace-Step1.5": "19671f406d603126926c1b7e2adc169acbcade22"
}
INFRA_SMOKE_BACKEND = "runpod_infra_smoke"
INFRA_SMOKE_ARTIFACT_CLASS = "INFRA_SMOKE_ARTIFACT"


def _gpu_identity() -> str:
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    value = completed.stdout.strip()
    if not value:
        raise RuntimeError("Runpod worker has no visible NVIDIA GPU")
    return value


def _runtime_identity() -> str:
    return f"{platform.system()}-{platform.machine()}-python{sys.version_info.major}.{sys.version_info.minor}"


def _request() -> dict:
    request = json.load(sys.stdin)
    if not isinstance(request, dict):
        raise ValueError("Runpod worker request must be a JSON object")
    return request


def _expected(backend: str):
    if backend == "hunyuanvideo_i2v":
        return HUNYUAN_SOURCE_REVISION, HUNYUAN_MODEL_SNAPSHOTS
    if backend == "ace_step":
        return ACE_STEP_SOURCE_REVISION, ACE_STEP_MODEL_SNAPSHOTS
    raise ValueError("Unsupported Runpod generative backend")


def _runtime_factory(backend: str):
    from app.services.isolated_generative_media_runtime import (
        create_ace_step_isolated_runtime,
        create_hunyuan_isolated_runtime,
    )
    if backend == "hunyuanvideo_i2v":
        return create_hunyuan_isolated_runtime
    if backend == "ace_step":
        return create_ace_step_isolated_runtime
    raise ValueError("Unsupported Runpod generative backend")


def _validate_target_request(request: dict) -> tuple[str, str, dict[str, str]]:
    payload = request.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("payload is required")
    target_backend = payload.get("target_backend")
    if target_backend not in {"hunyuanvideo_i2v", "ace_step"}:
        raise ValueError("INFRA_SMOKE target_backend is invalid")
    expected_source, expected_snapshots = _expected(target_backend)
    if request.get("source_revision") != expected_source:
        raise PermissionError("Runpod worker source revision request is not approved")
    if request.get("model_snapshots") != expected_snapshots:
        raise PermissionError("Runpod worker model snapshot request is not approved")
    return target_backend, expected_source, expected_snapshots


def _write_smoke_wav(output_root: Path) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "infra-smoke.wav"
    sample_rate = 8000
    frames = sample_rate // 4
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * frames)
    return path


def _execute_infra_smoke(request: dict) -> dict:
    target_backend, expected_source, expected_snapshots = _validate_target_request(request)
    gpu_identity = _gpu_identity()
    output_root = Path(
        request.get("payload", {}).get("output_dir")
        or ".runtime/generative-media/runpod-smoke"
    ).resolve()
    started = time.monotonic()
    artifact = _write_smoke_wav(output_root)
    return {
        "backend": INFRA_SMOKE_BACKEND,
        "target_backend": target_backend,
        "source_revision": expected_source,
        "model_snapshots": expected_snapshots,
        "gpu_identity": gpu_identity,
        "runtime_identity": _runtime_identity(),
        "artifact_ref": str(artifact),
        "seed": None,
        "generation_config": {
            "artifact_class": INFRA_SMOKE_ARTIFACT_CLASS,
            "synthetic": True,
            "sample_rate": 8000,
            "channels": 1,
            "duration_seconds": 0.25,
            "target_backend": target_backend,
        },
        "elapsed_seconds": time.monotonic() - started,
        "warnings": [
            "Synthetic infrastructure smoke only; no Hunyuan/ACE-Step weights loaded"
        ],
        "errors": [],
    }


def execute_worker_request(request: dict) -> dict:
    if not isinstance(request, dict):
        raise ValueError("Runpod worker request must be a JSON object")
    backend = request.get("backend")
    if backend == INFRA_SMOKE_BACKEND:
        if request.get("probe_only") is True:
            return {
                "backend": INFRA_SMOKE_BACKEND,
                "gpu_identity": _gpu_identity(),
                "runtime_identity": _runtime_identity(),
            }
        return _execute_infra_smoke(request)

    source_revision = request.get("source_revision")
    model_snapshots = request.get("model_snapshots")
    payload = request.get("payload")
    if not isinstance(backend, str):
        raise ValueError("backend is required")
    if not isinstance(source_revision, str):
        raise ValueError("source_revision is required")
    if not isinstance(model_snapshots, dict):
        raise ValueError("model_snapshots is required")
    if not isinstance(payload, dict):
        raise ValueError("payload is required")

    expected_source, expected_snapshots = _expected(backend)
    runtime_factory = _runtime_factory(backend)
    if source_revision != expected_source:
        raise PermissionError("Runpod worker source revision request is not approved")
    if model_snapshots != expected_snapshots:
        raise PermissionError("Runpod worker model snapshot request is not approved")

    gpu_identity = _gpu_identity()
    repo_root = Path(__file__).resolve().parents[3]
    runtime = runtime_factory(repo_root)
    result = runtime.generate(dict(payload))

    return {
        "backend": result.backend,
        "source_revision": expected_source,
        "model_snapshots": expected_snapshots,
        "gpu_identity": gpu_identity,
        "runtime_identity": _runtime_identity(),
        "artifact_ref": result.path,
        "seed": result.seed,
        "generation_config": dict(result.generation_config),
        "elapsed_seconds": result.elapsed_seconds,
        "warnings": list(result.warnings),
        "errors": [],
    }


def main() -> None:
    response = execute_worker_request(_request())
    sys.stdout.write(json.dumps(response, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
