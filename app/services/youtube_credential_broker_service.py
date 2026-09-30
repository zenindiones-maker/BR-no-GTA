from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    "ANALYTICS_READ":(
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ),
    "ANALYTICS_MONETARY_READ":(
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
    ),
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


READ_ONLY_BROKER_OPERATIONS = frozenset({
    "DATA_READ",
    "ANALYTICS_READ",
    "ANALYTICS_MONETARY_READ",
    "REPORTING_READ",
})

BROKER_CAPABILITY_SUBJECT_BY_OPERATION = {
    "DATA_READ": "capability:youtube.data.read",
    "ANALYTICS_READ": "capability:youtube.analytics.read",
    "ANALYTICS_MONETARY_READ": "capability:youtube.monetization.observe",
    "REPORTING_READ": "capability:youtube.reporting.read",
}

_WRITE_SCOPES = frozenset({
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
})


class LocalReadOnlyYouTubeCredentialBrokerRuntime:
    """Ephemeral runner-local read-only credential broker.

    This runtime is deliberately not a routing or authorization plane. It only
    converts already-authorized operation requests into opaque short-lived
    credential handles and executes a small allowlist of official YouTube read
    operations. Credential material never appears in handles or receipts.
    """

    def __init__(
        self,
        *,
        credentials_by_operation: dict[str, Any],
        data_service_factory: Callable[[Any], Any] | None = None,
        analytics_service_factory: Callable[[Any], Any] | None = None,
        reporting_service_factory: Callable[[Any], Any] | None = None,
        monetary_analytics_service_factory: Callable[[Any], Any] | None = None,
        handle_ttl_seconds: int = 600,
    ):
        self.credentials_by_operation = dict(credentials_by_operation)
        self.data_service_factory = data_service_factory
        self.analytics_service_factory = analytics_service_factory
        self.reporting_service_factory = reporting_service_factory
        self.monetary_analytics_service_factory = monetary_analytics_service_factory
        self.handle_ttl_seconds = int(handle_ttl_seconds)
        if self.handle_ttl_seconds < 30 or self.handle_ttl_seconds > 3600:
            raise ValueError("read-only broker handle TTL must be in [30,3600]")
        self._handles: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _known_credential_scopes(credentials: Any) -> set[str]:
        values = (
            getattr(credentials, "granted_scopes", None)
            or getattr(credentials, "scopes", None)
            or ()
        )
        return {str(item) for item in values if str(item)}

    def _credential_for(self, operation: str, scopes: tuple[str, ...]) -> Any:
        credentials = self.credentials_by_operation.get(operation)
        if credentials is None:
            raise YouTubeCredentialBrokerError(
                f"read-only broker credentials unavailable for {operation}"
            )
        has_scopes = getattr(credentials, "has_scopes", None)
        if not callable(has_scopes) or not has_scopes(list(scopes)):
            raise YouTubeCredentialBrokerError(
                f"read-only broker credential scope mismatch for {operation}"
            )
        known = self._known_credential_scopes(credentials)
        if known & _WRITE_SCOPES:
            raise YouTubeCredentialBrokerError(
                "read-only broker credential contains write-capable YouTube scope"
            )
        return credentials

    @staticmethod
    def _canonical_digest(value: dict[str, Any]) -> str:
        return __import__("hashlib").sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()

    def _issue_handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        operation = str(payload.get("operation") or "").upper()
        if operation not in READ_ONLY_BROKER_OPERATIONS:
            raise YouTubeCredentialBrokerError(
                "read-only broker refuses non-read-only YouTube operation"
            )
        authorization_ref = str(payload.get("authorization_ref") or "").strip()
        task_id = str(payload.get("task_id") or "").strip()
        resource_binding = payload.get("resource_binding")
        if not authorization_ref or not task_id or not isinstance(resource_binding, dict):
            raise YouTubeCredentialBrokerError(
                "read-only broker requires authorization_ref, task_id and resource_binding"
            )

        from app.services.harness_authorization_service import (
            consume_harness_authorization,
            validate_harness_authorization,
        )

        expected_subject = BROKER_CAPABILITY_SUBJECT_BY_OPERATION[operation]
        try:
            authorization = validate_harness_authorization(
                authorization_ref,
                expected_action="EXECUTION",
                expected_subject=expected_subject,
                expected_execution_id=task_id,
            )
        except PermissionError as exc:
            raise YouTubeCredentialBrokerError(
                "read-only broker Harness authorization rejected"
            ) from exc

        canonical_scopes = scopes_for_operation(operation)
        requested = tuple(str(x) for x in (payload.get("required_scopes") or ()))
        if set(requested) != set(canonical_scopes):
            raise YouTubeCredentialBrokerError(
                "read-only broker requires exact operation scope profile"
            )
        credentials = self._credential_for(operation, canonical_scopes)
        issued_at = datetime.now(timezone.utc)
        expires_at = issued_at + timedelta(seconds=self.handle_ttl_seconds)
        identity = {
            "operation": operation,
            "authorization_ref": authorization_ref,
            "task_id": task_id,
            "resource_binding": resource_binding,
            "issued_at": issued_at.isoformat(),
        }
        handle = "yt-handle-" + self._canonical_digest(identity)[:32]
        self._handles[handle] = {
            **identity,
            "expires_at": expires_at,
            "credentials": credentials,
            "scopes": canonical_scopes,
        }
        consume_harness_authorization(authorization)
        return {
            "credential_handle": handle,
            "operation": operation,
            "scopes": list(canonical_scopes),
            "expires_at": expires_at.isoformat(),
            "broker_identity": "br-no-gta-runner-local-readonly-v1",
        }

    def _resolve_handle(self, handle: str, operation: str) -> dict[str, Any]:
        record = self._handles.get(handle)
        if record is None:
            raise YouTubeCredentialBrokerError("unknown read-only broker handle")
        if record["operation"] != operation:
            raise YouTubeCredentialBrokerError("read-only broker handle operation mismatch")
        if record["expires_at"] <= datetime.now(timezone.utc):
            self._handles.pop(handle, None)
            raise YouTubeCredentialBrokerError("read-only broker handle expired")
        return record

    def _data_service(self, credentials: Any) -> Any:
        if self.data_service_factory is not None:
            return self.data_service_factory(credentials)
        from app.services.google_youtube_client import create_youtube_service
        return create_youtube_service(credentials)

    def _analytics_service(self, credentials: Any, *, monetary: bool = False) -> Any:
        if monetary and self.monetary_analytics_service_factory is not None:
            return self.monetary_analytics_service_factory(credentials)
        if not monetary and self.analytics_service_factory is not None:
            return self.analytics_service_factory(credentials)
        if monetary:
            from app.services.google_youtube_analytics_client import (
                create_youtube_monetary_analytics_service,
            )
            return create_youtube_monetary_analytics_service(credentials)
        from app.services.google_youtube_analytics_client import (
            create_youtube_analytics_service,
        )
        return create_youtube_analytics_service(credentials)

    def _reporting_service(self, credentials: Any) -> Any:
        if self.reporting_service_factory is not None:
            return self.reporting_service_factory(credentials)
        from app.services.google_youtube_reporting_client import (
            create_youtube_reporting_service,
        )
        return create_youtube_reporting_service(credentials)

    def _execute_data_read(self, credentials: Any, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action") or "")
        if action not in {"CHANNEL_MINE", "LATEST_UPLOAD"}:
            raise YouTubeCredentialBrokerError("unsupported DATA_READ broker action")
        from app.services.youtube_quota_service import quota_policy

        service = self._data_service(credentials)
        quota = quota_policy("youtube_data", "channels.list")
        response = service.channels().list(
            part="id,snippet,contentDetails,statistics,status",
            mine=True,
        ).execute()
        items = list(response.get("items") or ()) if isinstance(response, dict) else []
        channels = []
        for item in items:
            if not isinstance(item, dict):
                continue
            snippet = dict(item.get("snippet") or {})
            content = dict(item.get("contentDetails") or {})
            playlists = dict(content.get("relatedPlaylists") or {})
            channels.append({
                "channel_id": str(item.get("id") or ""),
                "title": str(snippet.get("title") or ""),
                "uploads_playlist_id": str(playlists.get("uploads") or ""),
            })
        if action == "LATEST_UPLOAD":
            uploads = channels[0]["uploads_playlist_id"] if channels else ""
            if not uploads:
                return {
                    "source": "YOUTUBE_DATA_API_V3",
                    "status": "NO_ELIGIBLE_DATA",
                    "video_id": None,
                }
            items_response = service.playlistItems().list(
                part="contentDetails,snippet",
                playlistId=uploads,
                maxResults=1,
            ).execute()
            items = list(items_response.get("items") or ()) if isinstance(items_response, dict) else []
            first = items[0] if items and isinstance(items[0], dict) else {}
            content = dict(first.get("contentDetails") or {})
            video_id = str(content.get("videoId") or "")
            return {
                "source": "YOUTUBE_DATA_API_V3",
                "status": "PASS" if video_id else "NO_ELIGIBLE_DATA",
                "video_id": video_id or None,
            }
        return {
            "source": "YOUTUBE_DATA_API_V3",
            "status": "PASS" if channels else "NO_ELIGIBLE_DATA",
            "channel_count": len(channels),
            "channels": channels,
            "quota_observation": {
                **quota,
                "remaining_estimate": None,
                "remaining_estimate_status": "UNKNOWN_NO_PROJECT_USAGE_SIGNAL",
            },
        }

    def _execute_analytics_read(
        self,
        credentials: Any,
        payload: dict[str, Any],
        *,
        monetary: bool = False,
    ) -> dict[str, Any]:
        action = str(payload.get("action") or "")
        start_date = str(payload.get("start_date") or "")
        end_date = str(payload.get("end_date") or "")
        if not start_date or not end_date:
            raise YouTubeCredentialBrokerError("analytics broker action requires date window")
        kwargs: dict[str, Any] = {
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
        }
        if monetary:
            if action != "CHANNEL_MONETARY_SUMMARY":
                raise YouTubeCredentialBrokerError(
                    "unsupported ANALYTICS_MONETARY_READ broker action"
                )
            metrics = (
                "estimatedRevenue,estimatedAdRevenue,cpm,playbackBasedCpm,"
                "monetizedPlaybacks,adImpressions"
            )
        elif action == "CHANNEL_SUMMARY":
            metrics = (
                "views,estimatedMinutesWatched,averageViewDuration,"
                "averageViewPercentage,subscribersGained,subscribersLost"
            )
        elif action == "RETENTION_SERIES":
            video_id = str(payload.get("video_id") or "").strip()
            if not video_id:
                raise YouTubeCredentialBrokerError(
                    "RETENTION_SERIES requires exact video_id"
                )
            metrics = "audienceWatchRatio,relativeRetentionPerformance"
            kwargs.update({
                "dimensions": "elapsedVideoTimeRatio",
                "filters": f"video=={video_id}",
                "sort": "elapsedVideoTimeRatio",
            })
        else:
            raise YouTubeCredentialBrokerError(
                "unsupported ANALYTICS_READ broker action"
            )
        kwargs["metrics"] = metrics
        response = self._analytics_service(credentials, monetary=monetary).reports().query(**kwargs).execute()
        if not isinstance(response, dict):
            raise YouTubeCredentialBrokerError("analytics broker received invalid response")
        headers = [
            str(item.get("name") or "")
            for item in (response.get("columnHeaders") or ())
            if isinstance(item, dict)
        ]
        rows = list(response.get("rows") or ())
        return {
            "source": "YOUTUBE_ANALYTICS_API",
            "status": "PASS" if rows else "NO_ELIGIBLE_DATA",
            "row_count": len(rows),
            "fields": headers,
        }

    def _execute_reporting_read(
        self,
        credentials: Any,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        action = str(payload.get("action") or "")
        if action != "JOBS_LIST":
            raise YouTubeCredentialBrokerError("unsupported REPORTING_READ broker action")
        response = self._reporting_service(credentials).jobs().list(
            includeSystemManaged=True,
            pageSize=100,
        ).execute()
        if not isinstance(response, dict):
            raise YouTubeCredentialBrokerError("reporting broker received invalid response")
        jobs = [
            {
                "job_id": str(item.get("id") or ""),
                "report_type_id": str(item.get("reportTypeId") or ""),
            }
            for item in (response.get("jobs") or ())
            if isinstance(item, dict)
        ]
        return {
            "source": "YOUTUBE_REPORTING_API",
            "status": "PASS" if jobs else "NO_ELIGIBLE_DATA",
            "job_count": len(jobs),
            "jobs": jobs,
        }

    def _execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        handle = str(payload.get("credential_handle") or "")
        operation = str(payload.get("operation") or "").upper()
        record = self._resolve_handle(handle, operation)
        self._handles.pop(handle, None)
        request_payload = payload.get("payload")
        if not isinstance(request_payload, dict):
            raise YouTubeCredentialBrokerError("broker operation payload must be an object")
        credentials = record["credentials"]
        if operation == "DATA_READ":
            receipt = self._execute_data_read(credentials, request_payload)
        elif operation == "ANALYTICS_READ":
            receipt = self._execute_analytics_read(credentials, request_payload)
        elif operation == "ANALYTICS_MONETARY_READ":
            receipt = self._execute_analytics_read(
                credentials, request_payload, monetary=True
            )
        elif operation == "REPORTING_READ":
            receipt = self._execute_reporting_read(credentials, request_payload)
        else:
            raise YouTubeCredentialBrokerError("unsupported read-only broker operation")
        return {"confirmed": True, "remote_receipt": receipt}

    def transport(
        self,
        endpoint: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        del headers
        if endpoint.endswith("/v1/youtube/credential-handles"):
            return self._issue_handle(payload)
        if endpoint.endswith("/v1/youtube/execute"):
            return self._execute(payload)
        raise YouTubeCredentialBrokerError("unknown read-only broker endpoint")
