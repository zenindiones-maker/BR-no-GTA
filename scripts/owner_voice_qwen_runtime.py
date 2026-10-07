from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from typing import Any

from app.services.owner_voice_qwen_runtime_service import (
    OwnerVoiceQwenRuntime,
    OwnerVoiceQwenRuntimeError,
)


HOST="127.0.0.1"
DEFAULT_PORT=18081
MAX_REQUEST_BYTES=64*1024


def _json_bytes(payload: dict[str,Any])->bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",",":"),
    ).encode("utf-8")


class OwnerVoiceRuntimeHandler(BaseHTTPRequestHandler):
    runtime: OwnerVoiceQwenRuntime|None=None
    auth_token: str=""

    server_version="BROwnerVoiceRuntime/1"
    sys_version=""

    def log_message(self, format: str, *args: Any)->None:
        return

    def _write_json(self,status: int,payload: dict[str,Any])->None:
        body=_json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self)->bool:
        expected="Bearer "+self.auth_token
        supplied=str(self.headers.get("Authorization") or "")
        return bool(
            self.auth_token
            and hmac.compare_digest(supplied,expected)
        )

    def do_GET(self)->None:
        if self.path!="/health":
            self._write_json(404,{"status":"NOT_FOUND"})
            return
        self._write_json(200,{
            "status":"READY" if self.runtime is not None and self.auth_token else "BLOCKED",
            "voice_identity_id":"BR_OWNER_V1",
            "provider":"qwen3-tts",
            "bind":HOST,
        })

    def do_POST(self)->None:
        if self.path!="/v1/speech":
            self._write_json(404,{"status":"NOT_FOUND"})
            return
        if not self._authorized():
            self._write_json(401,{"status":"UNAUTHORIZED"})
            return
        raw_length=str(self.headers.get("Content-Length") or "").strip()
        try:
            length=int(raw_length)
        except ValueError:
            self._write_json(400,{"status":"INVALID_CONTENT_LENGTH"})
            return
        if length<=0 or length>MAX_REQUEST_BYTES:
            self._write_json(413,{"status":"REQUEST_TOO_LARGE"})
            return
        raw=self.rfile.read(length)
        try:
            payload=json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError,json.JSONDecodeError):
            self._write_json(400,{"status":"INVALID_JSON"})
            return
        if not isinstance(payload,dict) or self.runtime is None:
            self._write_json(503,{"status":"VOICE_RUNTIME_UNAVAILABLE"})
            return
        try:
            result=self.runtime.synthesize(payload)
        except OwnerVoiceQwenRuntimeError as exc:
            self._write_json(422,{
                "status":"VOICE_SYNTHESIS_BLOCKED",
                "error":str(exc),
            })
            return
        receipt=result.receipt
        self.send_response(200)
        self.send_header("Content-Type","audio/wav")
        self.send_header("Content-Length",str(len(result.audio)))
        self.send_header("Cache-Control","no-store")
        headers={
            "X-BR-Voice-Receipt-Schema":receipt["schema"],
            "X-BR-Voice-Identity-Id":receipt["voice_identity_id"],
            "X-BR-Voice-Profile-SHA256":receipt["profile_sha256"],
            "X-BR-Voice-Prompt-SHA256":receipt["voice_prompt_sha256"],
            "X-BR-Voice-Reference-Set-SHA256":receipt["reference_set_sha256"],
            "X-BR-Voice-Provider":receipt["provider"],
            "X-BR-Voice-Model":receipt["model"],
            "X-BR-Voice-Model-Revision":receipt["model_revision"],
            "X-BR-Voice-Request-Id":receipt["request_id"],
            "X-BR-Voice-Audio-SHA256":receipt["audio_sha256"],
            "X-BR-Voice-Usage":receipt["usage"],
            "X-BR-Voice-Reference-Source":receipt["reference_source"],
            "X-BR-Voice-Accent-Locale":receipt["accent_locale"],
            "X-BR-Voice-Identity-Binding-Mode":receipt["identity_binding_mode"],
            "X-BR-Voice-Preset-Voice-Used":str(receipt["preset_voice_used"]).lower(),
            "X-BR-Voice-Generic-Fallback":str(receipt["generic_voice_fallback"]).lower(),
        }
        for key,value in headers.items():
            self.send_header(key,str(value))
        self.end_headers()
        self.wfile.write(result.audio)


def main()->int:
    token=str(os.environ.get("BR_VOICE_RUNTIME_TOKEN") or "").strip()
    if not token:
        raise SystemExit("BR_VOICE_RUNTIME_TOKEN is required")
    port=int(os.environ.get("BR_VOICE_RUNTIME_PORT") or DEFAULT_PORT)
    if not 1<=port<=65535:
        raise SystemExit("BR_VOICE_RUNTIME_PORT is invalid")
    OwnerVoiceRuntimeHandler.runtime=OwnerVoiceQwenRuntime()
    OwnerVoiceRuntimeHandler.auth_token=token
    server=ThreadingHTTPServer((HOST,port),OwnerVoiceRuntimeHandler)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
