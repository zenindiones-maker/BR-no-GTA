from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import time
from typing import Any, Callable
import urllib.error
import urllib.request

from app.services.runpod_generative_runtime import (
    RunpodExecutionHandle,
    RunpodExecutionRequest,
    RunpodExecutionResult,
    RunpodInfrastructureStatus,
    RunpodRuntimeError,
    RunpodRuntimeFailureReason,
    RunpodRuntimeUnavailable,
)


UrlOpen = Callable[..., Any]


class RunpodHttpExecutionClient:
    """Authenticated data-plane client for one already-provisioned Runpod Pod.

    Pod lifecycle remains outside this class (for example Runpod MCP). The
    application talks only to the bounded worker over the Runpod HTTPS proxy.
    No Runpod account credential is accepted or stored here.
    """

    def __init__(
        self,
        *,
        pod_id: str,
        bearer_token: str,
        port: int = 8000,
        urlopen: UrlOpen = urllib.request.urlopen,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        if not isinstance(pod_id, str) or not pod_id.strip():
            raise ValueError("Runpod pod_id is required")
        if not isinstance(bearer_token, str) or not bearer_token:
            raise ValueError("Runpod smoke bearer token is required")
        if port <= 0 or port > 65535:
            raise ValueError("Runpod worker port is invalid")
        if poll_interval_seconds <= 0:
            raise ValueError("Runpod poll interval must be positive")
        self._pod_id = pod_id.strip()
        self._token = bearer_token
        self._port = int(port)
        self._urlopen = urlopen
        self._poll_interval = float(poll_interval_seconds)
        self._base_url = f"https://{self._pod_id}-{self._port}.proxy.runpod.net"

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        data = None
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self._base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self._urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except (OSError, urllib.error.URLError) as exc:
            raise RunpodRuntimeUnavailable(
                RunpodRuntimeFailureReason.RUNPOD_UNAVAILABLE,
                "Runpod bounded worker HTTP transport is unavailable",
            ) from exc
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.RUNPOD_RESULT_INVALID,
                "Runpod bounded worker returned invalid JSON",
            ) from exc
        if not isinstance(decoded, dict):
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.RUNPOD_RESULT_INVALID,
                "Runpod bounded worker returned a non-object response",
            )
        return decoded

    def probe(self) -> RunpodInfrastructureStatus:
        payload = self._request_json("/health", timeout=15)
        if payload.get("status") != "READY":
            return RunpodInfrastructureStatus(available=False)
        gpu = payload.get("gpu_identity")
        runtime = payload.get("runtime_identity")
        if not isinstance(gpu, str) or not gpu.strip():
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.GPU_IDENTITY_MISSING,
                "Runpod bounded worker health response has no GPU identity",
            )
        if not isinstance(runtime, str) or not runtime.strip():
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.RUNTIME_IDENTITY_MISSING,
                "Runpod bounded worker health response has no runtime identity",
            )
        return RunpodInfrastructureStatus(
            available=True,
            execution_target_id=self._pod_id,
            gpu_identity=gpu,
            runtime_identity=runtime,
        )

    def submit(self, request: RunpodExecutionRequest) -> RunpodExecutionHandle:
        payload = self._request_json(
            "/execute",
            method="POST",
            payload={
                "backend": request.backend,
                "source_revision": request.source_revision,
                "model_snapshots": dict(request.model_snapshots),
                "payload": dict(request.payload),
                "output_media_kind": request.output_media_kind,
            },
            timeout=30,
        )
        execution_id = payload.get("execution_id")
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.RUNPOD_RESULT_INVALID,
                "Runpod bounded worker submission returned no execution_id",
            )
        return RunpodExecutionHandle(execution_id=execution_id, target_id=self._pod_id)

    def wait(
        self,
        handle: RunpodExecutionHandle,
        *,
        timeout_seconds: int,
    ) -> RunpodExecutionResult:
        deadline = time.monotonic() + timeout_seconds
        last: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            last = self._request_json(
                f"/executions/{handle.execution_id}",
                timeout=min(30.0, max(1.0, deadline - time.monotonic())),
            )
            status = last.get("status")
            if status in {"SUCCEEDED", "FAILED"}:
                break
            time.sleep(self._poll_interval)
        else:
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.RUNPOD_EXECUTION_FAILED,
                "Runpod bounded worker execution timed out",
            )
        assert last is not None
        required = {
            "execution_id",
            "status",
            "backend",
            "source_revision",
            "model_snapshots",
            "gpu_identity",
            "runtime_identity",
            "artifact_ref",
        }
        if not required.issubset(last):
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.RUNPOD_RESULT_INVALID,
                "Runpod bounded worker execution result is incomplete",
            )
        return RunpodExecutionResult(
            execution_id=str(last["execution_id"]),
            target_id=self._pod_id,
            status=str(last["status"]),
            backend=str(last["backend"]),
            source_revision=str(last["source_revision"]),
            model_snapshots=dict(last["model_snapshots"]),
            gpu_identity=str(last["gpu_identity"]),
            runtime_identity=str(last["runtime_identity"]),
            artifact_ref=str(last["artifact_ref"]),
            seed=last.get("seed"),
            generation_config=dict(last.get("generation_config") or {}),
            elapsed_seconds=last.get("elapsed_seconds"),
            warnings=tuple(last.get("warnings") or ()),
            errors=tuple(last.get("errors") or ()),
        )

    def materialize_artifact(
        self,
        handle: RunpodExecutionHandle,
        result: RunpodExecutionResult,
        *,
        destination_dir: Path,
    ) -> Path:
        if result.execution_id != handle.execution_id:
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.JOB_IDENTITY_MISMATCH,
                "Artifact request does not match execution identity",
            )
        destination_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(result.artifact_ref).suffix or ".bin"
        destination = destination_dir / f"artifact{suffix}"
        request = urllib.request.Request(
            self._base_url + f"/artifacts/{handle.execution_id}",
            headers={"Authorization": f"Bearer {self._token}"},
            method="GET",
        )
        try:
            with self._urlopen(request, timeout=60) as response:
                data = response.read()
        except (OSError, urllib.error.URLError) as exc:
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.ARTIFACT_UNAVAILABLE,
                "Runpod bounded worker artifact download failed",
            ) from exc
        if not data:
            raise RunpodRuntimeError(
                RunpodRuntimeFailureReason.ARTIFACT_UNAVAILABLE,
                "Runpod bounded worker artifact is empty",
            )
        destination.write_bytes(data)
        return destination
