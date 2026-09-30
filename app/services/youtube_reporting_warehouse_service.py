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
