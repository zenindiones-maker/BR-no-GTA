from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.google_youtube_reporting_client import (
    YOUTUBE_REPORTING_READ_SCOPE,
    YouTubeReportingScopeError,
    create_youtube_reporting_service,
)
from app.services.youtube_reporting_warehouse_service import (
    list_reporting_jobs,
    list_reporting_reports,
)


class _Credentials:
    def __init__(self, scopes):
        self._scopes=set(scopes)
    def has_scopes(self, requested):
        return set(requested).issubset(self._scopes)


class _Request:
    def __init__(self, payload):
        self.payload=payload
    def execute(self):
        return self.payload


class _Jobs:
    def __init__(self, payload):
        self.payload=payload
        self.kwargs=None
    def list(self, **kwargs):
        self.kwargs=kwargs
        return _Request(self.payload)


class _Reports:
    def __init__(self, payload):
        self.payload=payload
        self.kwargs=None
    def list(self, **kwargs):
        self.kwargs=kwargs
        return _Request(self.payload)


class _Reporting:
    def __init__(self, jobs_payload=None, reports_payload=None):
        self.jobs_api=_Jobs(jobs_payload or {"jobs":[]})
        self.reports_api=_Reports(reports_payload or {"reports":[]})
    def jobs(self):
        return self.jobs_api
    def reports(self):
        return self.reports_api


def test_reporting_client_requires_readonly_analytics_scope(monkeypatch):
    with pytest.raises(YouTubeReportingScopeError):
        create_youtube_reporting_service(_Credentials(()))

    captured={}
    def fake_build(name, version, credentials):
        captured.update(name=name, version=version, credentials=credentials)
        return object()
    monkeypatch.setattr("app.services.google_youtube_reporting_client.build", fake_build)
    creds=_Credentials((YOUTUBE_REPORTING_READ_SCOPE,))
    service=create_youtube_reporting_service(creds)
    assert service is not None
    assert captured["name"]=="youtubereporting"
    assert captured["version"]=="v1"


def test_list_reporting_jobs_includes_system_managed_and_returns_no_eligible_data_when_empty():
    service=_Reporting(jobs_payload={"jobs":[]})
    result=list_reporting_jobs(service=service)
    assert service.jobs_api.kwargs=={
        "includeSystemManaged": True,
        "pageSize": 100,
    }
    assert result["status"]=="NO_ELIGIBLE_DATA"
    assert result["jobs"]==[]


def test_list_reporting_jobs_returns_only_typed_job_metadata():
    service=_Reporting(jobs_payload={
        "jobs":[{
            "id":"job-1",
            "name":"system managed reach",
            "reportTypeId":"channel_reach_basic_a1",
            "createTime":"2026-09-01T00:00:00Z",
            "expireTime":"2027-09-01T00:00:00Z",
            "systemManaged":True,
        }]
    })
    result=list_reporting_jobs(service=service)
    assert result["status"]=="PASS"
    assert result["jobs"]==[{
        "job_id":"job-1",
        "name":"system managed reach",
        "report_type_id":"channel_reach_basic_a1",
        "create_time":"2026-09-01T00:00:00Z",
        "expire_time":"2027-09-01T00:00:00Z",
        "system_managed":True,
    }]


def test_list_reports_uses_created_after_for_backfill_safe_incremental_ingestion():
    service=_Reporting(reports_payload={
        "reports":[{
            "id":"report-2",
            "jobId":"job-1",
            "startTime":"2026-09-28T00:00:00Z",
            "endTime":"2026-09-29T00:00:00Z",
            "createTime":"2026-09-30T05:00:00Z",
            "downloadUrl":"https://youtubereporting.googleapis.com/v1/media/report-2?alt=media",
        }]
    })
    result=list_reporting_reports(
        service=service,
        job_id="job-1",
        created_after="2026-09-30T04:00:00Z",
    )
    assert service.reports_api.kwargs=={
        "jobId":"job-1",
        "createdAfter":"2026-09-30T04:00:00Z",
        "pageSize":100,
    }
    assert result["status"]=="PASS"
    assert result["reports"][0]["report_id"]=="report-2"
    assert result["reports"][0]["created_at"]=="2026-09-30T05:00:00Z"
    assert result["cursor"]["newest_created_at"]=="2026-09-30T05:00:00Z"
    assert result["cursor"]["newest_report_id"]=="report-2"


def test_list_reports_empty_is_no_eligible_data_not_zero_or_failure():
    service=_Reporting(reports_payload={"reports":[]})
    result=list_reporting_reports(
        service=service,
        job_id="job-1",
        created_after="2026-09-30T04:00:00Z",
    )
    assert result["status"]=="NO_ELIGIBLE_DATA"
    assert result["reports"]==[]
