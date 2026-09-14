from __future__ import annotations

import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
import uuid

import importlib.util

_WORKER_PATH = Path(__file__).with_name("worker_once.py")
_SPEC = importlib.util.spec_from_file_location("br_runpod_worker_once", _WORKER_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("Unable to load Runpod worker module")
_WORKER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_WORKER)
execute_worker_request = _WORKER.execute_worker_request


TOKEN = os.environ.get("BR_RUNPOD_SMOKE_TOKEN", "")
PORT = int(os.environ.get("BR_RUNPOD_SMOKE_PORT", "8000"))
_EXECUTIONS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _authorized(handler: BaseHTTPRequestHandler) -> bool:
    value = handler.headers.get("Authorization") or ""
    return bool(TOKEN) and value == f"Bearer {TOKEN}"


class Handler(BaseHTTPRequestHandler):
    server_version = "BRRunpodSmoke/1"

    def log_message(self, fmt, *args):
        return

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _check_auth(self) -> bool:
        if _authorized(self):
            return True
        self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        return False

    def do_GET(self):
        if not self._check_auth():
            return
        if self.path == "/health":
            try:
                probe = execute_worker_request({"backend": "runpod_infra_smoke", "probe_only": True})
            except Exception as exc:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"status": "NOT_READY", "error": str(exc)})
                return
            self._json(HTTPStatus.OK, {
                "status": "READY",
                "gpu_identity": probe["gpu_identity"],
                "runtime_identity": probe["runtime_identity"],
            })
            return
        if self.path.startswith("/executions/"):
            execution_id = self.path.rsplit("/", 1)[-1]
            with _LOCK:
                item = _EXECUTIONS.get(execution_id)
            if item is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "execution not found"})
                return
            self._json(HTTPStatus.OK, {k: v for k, v in item.items() if k != "artifact_path"})
            return
        if self.path.startswith("/artifacts/"):
            execution_id = self.path.rsplit("/", 1)[-1]
            with _LOCK:
                item = _EXECUTIONS.get(execution_id)
            if item is None or item.get("status") != "SUCCEEDED":
                self._json(HTTPStatus.NOT_FOUND, {"error": "artifact unavailable"})
                return
            path = Path(item["artifact_path"])
            if not path.is_file():
                self._json(HTTPStatus.NOT_FOUND, {"error": "artifact missing"})
                return
            data = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self):
        if not self._check_auth():
            return
        if self.path != "/execute":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0 or length > 1024 * 1024:
                raise ValueError("invalid request length")
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("request must be object")
        except Exception as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        execution_id = uuid.uuid4().hex
        with _LOCK:
            _EXECUTIONS[execution_id] = {"execution_id": execution_id, "status": "RUNNING"}
        thread = threading.Thread(target=_execute, args=(execution_id, request), daemon=True)
        thread.start()
        self._json(HTTPStatus.ACCEPTED, {"execution_id": execution_id})


def _execute(execution_id: str, request: dict) -> None:
    started = time.monotonic()
    try:
        result = execute_worker_request(request)
        artifact_path = str(result["artifact_ref"])
        payload = dict(result)
        payload["execution_id"] = execution_id
        payload["status"] = "SUCCEEDED"
        payload["elapsed_seconds"] = float(result.get("elapsed_seconds") or (time.monotonic() - started))
        payload["artifact_path"] = artifact_path
    except Exception as exc:
        payload = {
            "execution_id": execution_id,
            "status": "FAILED",
            "backend": request.get("backend", ""),
            "source_revision": request.get("source_revision", ""),
            "model_snapshots": request.get("model_snapshots") or {},
            "gpu_identity": "",
            "runtime_identity": "",
            "artifact_ref": "",
            "warnings": [],
            "errors": [f"{type(exc).__name__}: {exc}"],
            "elapsed_seconds": time.monotonic() - started,
        }
    with _LOCK:
        _EXECUTIONS[execution_id] = payload


def main() -> None:
    if not TOKEN:
        raise RuntimeError("BR_RUNPOD_SMOKE_TOKEN is required")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
