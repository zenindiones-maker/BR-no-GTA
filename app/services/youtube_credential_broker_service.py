from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError


BROKER_SCHEMA="YouTubeCredentialBroker/v1"
HANDLE_SCHEMA="YouTubeCredentialHandle/v1"

OPERATION_SCOPES: dict[str,tuple[str,...]]={
    "DATA_READ":("https://www.googleapis.com/auth/youtube.readonly",),
    "VIDEO_UPLOAD":("https://www.googleapis.com/auth/youtube.upload",),
    "VIDEO_METADATA_UPDATE":("https://www.googleapis.com/auth/youtube",),
    "THUMBNAIL_SET":("https://www.googleapis.com/auth/youtube.upload",),
    "PLAYLIST_MANAGE":("https://www.googleapis.com/auth/youtube",),
    "COMMENT_READ":("https://www.googleapis.com/auth/youtube.readonly",),
    "COMMENT_REPLY":("https://www.googleapis.com/auth/youtube.force-ssl",),
    "ANALYTICS_READ":("https://www.googleapis.com/auth/yt-analytics.readonly",),
    "ANALYTICS_MONETARY_READ":("https://www.googleapis.com/auth/yt-analytics-monetary.readonly",),
    "REPORTING_READ":("https://www.googleapis.com/auth/yt-analytics.readonly",),
    "REPORTING_MONETARY_READ":("https://www.googleapis.com/auth/yt-analytics-monetary.readonly",),
}


class YouTubeCredentialBrokerError(RuntimeError):
    pass


class YouTubeRemoteStateUnknown(YouTubeCredentialBrokerError):
    pass


@dataclass(frozen=True)
class YouTubeCredentialHandle:
    credential_handle: str
    operation: str
    scopes: tuple[str,...]
    expires_at: str
    broker_identity: str
    schema: str=HANDLE_SCHEMA


BrokerTransport=Callable[[str,dict[str,Any],dict[str,str]],dict[str,Any]]


def scopes_for_operation(operation: str) -> tuple[str,...]:
    key=str(operation or "").upper()
    if key not in OPERATION_SCOPES:
        raise PermissionError("YouTube operation has no least-privilege scope profile")
    return OPERATION_SCOPES[key]


def _read_identity_token(path: str | None) -> str | None:
    if not path:
        return None
    source=Path(path)
    if not source.is_file() or source.is_symlink():
        raise YouTubeCredentialBrokerError("broker workload identity token file unavailable")
    token=source.read_text(encoding="utf-8").strip()
    if not token:
        raise YouTubeCredentialBrokerError("broker workload identity token empty")
    return token


def _transport(endpoint: str,payload: dict[str,Any],headers: dict[str,str]) -> dict[str,Any]:
    body=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode("utf-8")
    req=urllib_request.Request(endpoint,data=body,headers={"Content-Type":"application/json",**headers},method="POST")
    try:
        with urllib_request.urlopen(req,timeout=20) as response:
            raw=response.read(256*1024)
    except HTTPError as exc:
        raise YouTubeCredentialBrokerError(f"broker HTTP {exc.code}") from exc
    except URLError as exc:
        raise YouTubeCredentialBrokerError("broker network unavailable") from exc
    try:
        value=json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise YouTubeCredentialBrokerError("broker returned invalid JSON") from exc
    if not isinstance(value,dict):
        raise YouTubeCredentialBrokerError("broker returned non-object")
    return value


class YouTubeCredentialBrokerClient:
    """Opaque, short-lived Google/YouTube credential handle boundary.

    Refresh/access credentials remain broker-side. Agent/model/task artifacts only
    receive operation-bound handles and non-secret remote receipts.
    """

    def __init__(
        self,
        *,
        base_url: str | None=None,
        identity_token_file: str | None=None,
        transport: BrokerTransport | None=None,
    ):
        self.base_url=str(base_url or os.getenv("YOUTUBE_CREDENTIAL_BROKER_URL") or "").rstrip("/")
        self.identity_token_file=(
            identity_token_file if identity_token_file is not None
            else os.getenv("YOUTUBE_CREDENTIAL_BROKER_IDENTITY_TOKEN_FILE")
        )
        self.transport=transport or _transport
        if self.transport is _transport and not self.base_url:
            raise YouTubeCredentialBrokerError("YOUTUBE_CREDENTIAL_BROKER_URL is required")

    def _headers(self) -> dict[str,str]:
        token=_read_identity_token(self.identity_token_file)
        return {"Authorization":f"Bearer {token}"} if token else {}

    @staticmethod
    def _reject_secret_material(payload: dict[str,Any]) -> None:
        forbidden={
            "token","access_token","refresh_token","client_secret","private_key",
            "authorization_code","oauth_token","google_credentials",
        }
        keys={str(k).lower() for k in payload}
        if keys & forbidden:
            raise YouTubeCredentialBrokerError("credential broker attempted to expose secret material")

    def request_handle(
        self,
        *,
        operation: str,
        authorization_ref: str,
        task_id: str,
        resource_binding: dict[str,Any],
        required_scopes: tuple[str,...] | None=None,
    ) -> YouTubeCredentialHandle:
        canonical=set(scopes_for_operation(operation))
        scopes=tuple(required_scopes or canonical)
        if not set(scopes).issubset(canonical):
            raise PermissionError("requested YouTube OAuth scopes exceed operation profile")
        payload={
            "schema":BROKER_SCHEMA,
            "operation":operation,
            "authorization_ref":authorization_ref,
            "task_id":task_id,
            "resource_binding":resource_binding,
            "required_scopes":list(scopes),
        }
        result=self.transport(
            self.base_url+"/v1/youtube/credential-handles",payload,self._headers()
        )
        self._reject_secret_material(result)
        handle=str(result.get("credential_handle") or "")
        expires=str(result.get("expires_at") or "")
        identity=str(result.get("broker_identity") or "")
        returned=tuple(str(x) for x in (result.get("scopes") or ()))
        if not handle or not expires or not identity or set(returned)!=set(scopes):
            raise YouTubeCredentialBrokerError("credential broker handle response invalid")
        parsed=datetime.fromisoformat(expires.replace("Z","+00:00"))
        if parsed.tzinfo is None or parsed.astimezone(timezone.utc)<=datetime.now(timezone.utc):
            raise YouTubeCredentialBrokerError("credential broker returned expired handle")
        return YouTubeCredentialHandle(
            credential_handle=handle,operation=operation,scopes=scopes,
            expires_at=expires,broker_identity=identity,
        )

    def execute(
        self,
        *,
        handle: YouTubeCredentialHandle,
        operation_id: str,
        payload_digest: str,
        payload: dict[str,Any],
    ) -> dict[str,Any]:
        request_payload={
            "schema":"YouTubeBrokerOperation/v1",
            "credential_handle":handle.credential_handle,
            "operation":handle.operation,
            "operation_id":operation_id,
            "payload_digest":payload_digest,
            "payload":payload,
        }
        try:
            result=self.transport(
                self.base_url+"/v1/youtube/execute",request_payload,self._headers()
            )
        except YouTubeCredentialBrokerError as exc:
            raise YouTubeRemoteStateUnknown(
                "YouTube broker execution outcome ambiguous; reconciliation required"
            ) from exc
        self._reject_secret_material(result)
        if result.get("confirmed") is not True:
            raise YouTubeRemoteStateUnknown("YouTube broker did not confirm remote operation")
        receipt=result.get("remote_receipt")
        if not isinstance(receipt,dict) or not receipt:
            raise YouTubeRemoteStateUnknown("YouTube broker confirmed without remote receipt")
        return receipt
