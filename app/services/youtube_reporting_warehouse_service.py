from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import csv
import io
import json
from typing import Any, Iterable

from app.database.youtube_intelligence_repository import persist_reporting_snapshot


REACH_BASIC_REPORT = "channel_reach_basic_a1"
REACH_COMBINED_REPORT = "channel_reach_combined_a1"


@dataclass(frozen=True)
class ReportingSnapshot:
    snapshot_id: str
    report_id: str
    report_type: str
    period_start: str
    period_end: str
    retrieved_at: str
    revision: int
    backfill_state: str
    content_digest: str
    row_count: int
    schema: str = "YouTubeReportingSnapshot/v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _digest(payload: Any) -> str:
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def parse_reporting_csv(csv_text: str) -> list[dict[str, str]]:
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise ValueError("Reporting API CSV payload is required")
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("Reporting API CSV has no header")
    return [dict(row) for row in reader]


def normalize_reach_rows(
    rows: Iterable[dict[str, Any]],
    *,
    report_type: str,
) -> list[dict[str, Any]]:
    required = {"date", "channel_id", "video_id", "video_thumbnail_impressions", "video_thumbnail_impressions_ctr"}
    if report_type == REACH_COMBINED_REPORT:
        required.update({"traffic_source_type", "traffic_source_detail", "device_type"})
    normalized=[]
    for raw in rows:
        missing=[field for field in required if field not in raw]
        if missing:
            raise ValueError("reach report missing fields: " + ",".join(sorted(missing)))
        item = {
            "date": str(raw["date"]),
            "channel_id": str(raw["channel_id"]),
            "video_id": str(raw["video_id"]),
            "video_thumbnail_impressions": int(float(raw["video_thumbnail_impressions"] or 0)),
            "video_thumbnail_impressions_ctr": float(raw["video_thumbnail_impressions_ctr"] or 0.0),
        }
        for field in (
            "traffic_source_type",
            "traffic_source_detail",
            "operating_system",
            "device_type",
        ):
            if field in raw:
                item[field] = raw.get(field)
        normalized.append(item)
    return normalized


def persist_report_revision(
    *,
    report_id: str,
    report_type: str,
    period_start: str,
    period_end: str,
    revision: int,
    backfill_state: str,
    rows: list[dict[str, Any]],
    evidence_refs: tuple[str, ...] = (),
    retrieved_at: str | None = None,
) -> ReportingSnapshot:
    if revision < 1:
        raise ValueError("report revision must be >= 1")
    if backfill_state not in {"INITIAL", "BACKFILLED", "FINAL", "UNKNOWN"}:
        raise ValueError("invalid reporting backfill state")
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    payload = {
        "schema": "YouTubeReportingWarehouseRows/v1",
        "report_id": report_id,
        "report_type": report_type,
        "period_start": period_start,
        "period_end": period_end,
        "revision": revision,
        "backfill_state": backfill_state,
        "rows": rows,
    }
    digest = _digest(payload)
    snapshot_id = f"yt-report-{digest[:24]}"
    row,_ = persist_reporting_snapshot(
        snapshot_id=snapshot_id,
        report_id=report_id,
        report_type=report_type,
        period_start=period_start,
        period_end=period_end,
        retrieved_at=retrieved,
        revision=revision,
        backfill_state=backfill_state,
        payload=payload,
        evidence_refs=evidence_refs,
    )
    return ReportingSnapshot(
        snapshot_id=row["snapshot_id"],
        report_id=row["report_id"],
        report_type=row["report_type"],
        period_start=row["period_start"],
        period_end=row["period_end"],
        retrieved_at=row["retrieved_at"],
        revision=int(row["revision"]),
        backfill_state=row["backfill_state"],
        content_digest=row["content_digest"],
        row_count=len(rows),
    )


def list_reporting_jobs(
    *,
    service: Any,
    page_size: int = 100,
) -> dict[str, Any]:
    if page_size < 1 or page_size > 100:
        raise ValueError("Reporting jobs page_size must be in [1,100]")
    response = service.jobs().list(
        includeSystemManaged=True,
        pageSize=page_size,
    ).execute()
    if not isinstance(response, dict):
        raise RuntimeError("YouTube Reporting jobs.list returned invalid response")
    jobs = []
    for raw in response.get("jobs") or ():
        if not isinstance(raw, dict):
            continue
        jobs.append({
            "job_id": str(raw.get("id") or ""),
            "name": str(raw.get("name") or ""),
            "report_type_id": str(raw.get("reportTypeId") or ""),
            "create_time": str(raw.get("createTime") or ""),
            "expire_time": str(raw.get("expireTime") or ""),
            "system_managed": bool(raw.get("systemManaged")),
        })
    return {
        "schema": "YouTubeReportingJobsRead/v1",
        "status": "PASS" if jobs else "NO_ELIGIBLE_DATA",
        "jobs": jobs,
        "next_page_token": response.get("nextPageToken"),
        "source": "YOUTUBE_REPORTING_API",
    }


def list_reporting_reports(
    *,
    service: Any,
    job_id: str,
    created_after: str | None = None,
    start_time_at_or_after: str | None = None,
    page_size: int = 100,
) -> dict[str, Any]:
    job = str(job_id or "").strip()
    if not job:
        raise ValueError("Reporting job_id is required")
    if page_size < 1 or page_size > 100:
        raise ValueError("Reporting reports page_size must be in [1,100]")
    kwargs: dict[str, Any] = {"jobId": job, "pageSize": page_size}
    if created_after:
        kwargs["createdAfter"] = str(created_after)
    if start_time_at_or_after:
        kwargs["startTimeAtOrAfter"] = str(start_time_at_or_after)
    response = service.reports().list(**kwargs).execute()
    if not isinstance(response, dict):
        raise RuntimeError("YouTube Reporting reports.list returned invalid response")
    reports = []
    for raw in response.get("reports") or ():
        if not isinstance(raw, dict):
            continue
        reports.append({
            "report_id": str(raw.get("id") or ""),
            "job_id": str(raw.get("jobId") or job),
            "start_time": str(raw.get("startTime") or ""),
            "end_time": str(raw.get("endTime") or ""),
            "created_at": str(raw.get("createTime") or ""),
            "download_url": str(raw.get("downloadUrl") or ""),
        })
    reports.sort(key=lambda item: (item["created_at"], item["report_id"]))
    newest = reports[-1] if reports else None
    return {
        "schema": "YouTubeReportingReportsRead/v1",
        "status": "PASS" if reports else "NO_ELIGIBLE_DATA",
        "reports": reports,
        "cursor": {
            "newest_created_at": newest["created_at"] if newest else created_after,
            "newest_report_id": newest["report_id"] if newest else None,
        },
        "next_page_token": response.get("nextPageToken"),
        "source": "YOUTUBE_REPORTING_API",
    }
