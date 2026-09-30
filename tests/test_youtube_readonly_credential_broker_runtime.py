from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.youtube_credential_broker_service import (
    LocalReadOnlyYouTubeCredentialBrokerRuntime,
    YouTubeCredentialBrokerClient,
    YouTubeCredentialBrokerError,
)




@pytest.fixture(autouse=True)
def _harness_auth_db(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_TEST_DATABASE", str(tmp_path / "broker-harness.db"))
    from app.database.schema import initialize_schema
    initialize_schema()


def _authorization(operation: str, task_id: str = "task-1") -> str:
    from app.services.harness_authorization_service import issue_harness_authorization

    subjects = {
        "DATA_READ": "capability:youtube.data.read",
        "ANALYTICS_READ": "capability:youtube.analytics.read",
        "ANALYTICS_MONETARY_READ": "capability:youtube.monetization.observe",
        "REPORTING_READ": "capability:youtube.reporting.read",
    }
    auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=subjects[operation],
        execution_id=task_id,
        lineage={
            "mission_type": "BLOCK_1_CERTIFICATION_TEST",
            "capability_id": subjects[operation].split("capability:", 1)[1],
        },
    )
    return auth.authorization_id


class _Credentials:
    def __init__(self, scopes):
        self.scopes=tuple(scopes)
    def has_scopes(self, requested):
        return set(requested).issubset(set(self.scopes))


class _Request:
    def __init__(self, payload):
        self.payload=payload
    def execute(self):
        return self.payload


class _Channels:
    def list(self, **kwargs):
        assert kwargs["mine"] is True
        assert "contentDetails" in kwargs["part"]
        return _Request({"items":[{"id":"channel-1","snippet":{"title":"BR no GTA 6"}}]})


class _DataService:
    def channels(self):
        return _Channels()


class _AnalyticsReports:
    def query(self, **kwargs):
        if kwargs.get("dimensions")=="elapsedVideoTimeRatio":
            return _Request({
                "columnHeaders":[
                    {"name":"elapsedVideoTimeRatio"},
                    {"name":"audienceWatchRatio"},
                    {"name":"relativeRetentionPerformance"},
                ],
                "rows":[[0.0,1.0,0.1],[1.0,0.4,-0.1]],
            })
        return _Request({
            "columnHeaders":[{"name":"views"},{"name":"estimatedMinutesWatched"}],
            "rows":[[123,456]],
        })


class _AnalyticsService:
    def reports(self):
        return _AnalyticsReports()


class _ReportingJobs:
    def list(self, **kwargs):
        assert kwargs["includeSystemManaged"] is True
        return _Request({"jobs":[{"id":"job-1","reportTypeId":"channel_reach_basic_a1"}]})


class _ReportingService:
    def jobs(self):
        return _ReportingJobs()


def _runtime():
    read_scopes=(
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    )
    monetary_scopes=(
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
    )
    return LocalReadOnlyYouTubeCredentialBrokerRuntime(
        credentials_by_operation={
            "DATA_READ":_Credentials(read_scopes),
            "ANALYTICS_READ":_Credentials(read_scopes),
            "REPORTING_READ":_Credentials(read_scopes),
            "ANALYTICS_MONETARY_READ":_Credentials(monetary_scopes),
        },
        data_service_factory=lambda creds:_DataService(),
        analytics_service_factory=lambda creds:_AnalyticsService(),
        reporting_service_factory=lambda creds:_ReportingService(),
    )


def test_local_readonly_broker_issues_opaque_handle_and_never_returns_secret_material():
    runtime=_runtime()
    client=YouTubeCredentialBrokerClient(
        base_url="http://broker.local",
        transport=runtime.transport,
    )
    handle=client.request_handle(
        operation="DATA_READ",
        authorization_ref=_authorization("DATA_READ"),
        task_id="task-1",
        resource_binding={"channel":"MINE"},
    )
    assert handle.credential_handle.startswith("yt-handle-")
    assert "token" not in handle.credential_handle.lower()

    receipt=client.execute(
        handle=handle,
        operation_id="op-1",
        payload_digest="a"*64,
        payload={"action":"CHANNEL_MINE"},
    )
    assert receipt["source"]=="YOUTUBE_DATA_API_V3"
    assert receipt["channel_count"]==1
    assert receipt["quota_observation"]["operation"]=="channels.list"
    assert receipt["quota_observation"]["remaining_estimate"] is None
    assert receipt["quota_observation"]["remaining_estimate_status"]=="UNKNOWN_NO_PROJECT_USAGE_SIGNAL"
    assert "access_token" not in repr(receipt).lower()
    assert "refresh_token" not in repr(receipt).lower()


def test_local_readonly_broker_rejects_write_operations_even_if_caller_asks():
    runtime=_runtime()
    client=YouTubeCredentialBrokerClient(
        base_url="http://broker.local",
        transport=runtime.transport,
    )
    with pytest.raises((PermissionError, YouTubeCredentialBrokerError)):
        client.request_handle(
            operation="VIDEO_UPLOAD",
            authorization_ref="auth-1",
            task_id="task-1",
            resource_binding={"channel":"MINE"},
        )


def test_local_readonly_broker_requires_exact_operation_scope_profile():
    runtime=LocalReadOnlyYouTubeCredentialBrokerRuntime(
        credentials_by_operation={
            "ANALYTICS_READ":_Credentials((
                "https://www.googleapis.com/auth/youtube.readonly",
            )),
        },
        data_service_factory=lambda creds:_DataService(),
        analytics_service_factory=lambda creds:_AnalyticsService(),
        reporting_service_factory=lambda creds:_ReportingService(),
    )
    client=YouTubeCredentialBrokerClient(
        base_url="http://broker.local",
        transport=runtime.transport,
    )
    with pytest.raises(YouTubeCredentialBrokerError, match="scope"):
        client.request_handle(
            operation="ANALYTICS_READ",
            authorization_ref=_authorization("ANALYTICS_READ"),
            task_id="task-1",
            resource_binding={"channel":"MINE"},
        )


def test_local_readonly_broker_runs_analytics_retention_and_reporting_allowlist():
    runtime=_runtime()
    client=YouTubeCredentialBrokerClient(
        base_url="http://broker.local",
        transport=runtime.transport,
    )
    for operation, action, expected_source in (
        ("ANALYTICS_READ","CHANNEL_SUMMARY","YOUTUBE_ANALYTICS_API"),
        ("ANALYTICS_READ","RETENTION_SERIES","YOUTUBE_ANALYTICS_API"),
        ("REPORTING_READ","JOBS_LIST","YOUTUBE_REPORTING_API"),
    ):
        handle=client.request_handle(
            operation=operation,
            authorization_ref=_authorization(operation),
            task_id="task-1",
            resource_binding={"channel":"MINE","video_id":"v1"},
        )
        payload={"action":action,"start_date":"2026-09-01","end_date":"2026-09-29","video_id":"v1"}
        receipt=client.execute(
            handle=handle,
            operation_id=f"op-{action.lower()}",
            payload_digest="b"*64,
            payload=payload,
        )
        assert receipt["source"]==expected_source
        assert receipt["status"] in {"PASS","NO_ELIGIBLE_DATA"}



def test_local_readonly_broker_rejects_fabricated_harness_authorization():
    runtime=_runtime()
    client=YouTubeCredentialBrokerClient(
        base_url="http://broker.local",
        transport=runtime.transport,
    )
    with pytest.raises(YouTubeCredentialBrokerError, match="authorization"):
        client.request_handle(
            operation="DATA_READ",
            authorization_ref="fabricated",
            task_id="task-fabricated",
            resource_binding={"channel":"MINE"},
        )



def test_local_readonly_broker_handle_is_one_shot():
    runtime=_runtime()
    client=YouTubeCredentialBrokerClient(
        base_url="http://broker.local",
        transport=runtime.transport,
    )
    handle=client.request_handle(
        operation="DATA_READ",
        authorization_ref=_authorization("DATA_READ"),
        task_id="task-1",
        resource_binding={"channel":"MINE"},
    )
    client.execute(
        handle=handle,
        operation_id="one-shot-1",
        payload_digest="c"*64,
        payload={"action":"CHANNEL_MINE"},
    )
    with pytest.raises(YouTubeCredentialBrokerError, match="ambiguous"):
        client.execute(
            handle=handle,
            operation_id="one-shot-2",
            payload_digest="d"*64,
            payload={"action":"CHANNEL_MINE"},
        )
