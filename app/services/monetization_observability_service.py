from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable


YOUTUBE_ANALYTICS_MONETARY_SCOPE = "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"
MONETIZATION_CAPABILITY_ID = "youtube.monetization.observe"
MONETIZATION_EXECUTOR_BINDING = "app.services.monetization_observability_service.execute_monetization_observability_capability"

CORE_METRICS = (
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "subscribersGained",
    "subscribersLost",
)
MONETARY_METRICS = (
    "estimatedRevenue",
    "estimatedAdRevenue",
    "grossRevenue",
    "cpm",
    "playbackBasedCpm",
    "monetizedPlaybacks",
)


@dataclass(frozen=True)
class MetricValue:
    status: str
    value: Any = None
    reason: str | None = None


@dataclass(frozen=True)
class ChannelMonetizationSnapshot:
    timestamp: str
    period: dict[str, str]
    currency: str | None
    views: MetricValue
    watch_time: MetricValue
    subscribers_delta: MetricValue
    estimated_revenue: MetricValue
    rpm_if_available: MetricValue
    cpm_if_available: MetricValue
    monetized_playbacks_if_available: MetricValue
    top_videos: tuple[dict[str, Any], ...]
    revenue_by_video_if_available: tuple[dict[str, Any], ...]
    traffic_summary: tuple[dict[str, Any], ...]
    data_source: str
    data_freshness: str
    evidence: tuple[dict[str, Any], ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _metric(by_name: dict[str, Any], name: str, *, reason: str | None = None) -> MetricValue:
    if name in by_name and by_name[name] is not None:
        return MetricValue(status="VALUE", value=by_name[name])
    return MetricValue(status="UNAVAILABLE", value=None, reason=reason or "metric_not_returned_by_api")


def _row_map(response: dict[str, Any]) -> dict[str, Any]:
    headers = response.get("columnHeaders") or []
    rows = response.get("rows") or []
    names = [item.get("name") for item in headers if isinstance(item, dict)]
    values = rows[0] if rows and isinstance(rows[0], list) else []
    return {name: values[index] for index, name in enumerate(names) if isinstance(name, str) and index < len(values)}


def normalize_monetization_snapshot(
    response: dict[str, Any],
    *,
    start_date: str,
    end_date: str,
    currency: str | None = None,
    retrieved_at: str | None = None,
    top_videos: tuple[dict[str, Any], ...] = (),
    revenue_by_video: tuple[dict[str, Any], ...] = (),
    traffic_summary: tuple[dict[str, Any], ...] = (),
    limitations: tuple[str, ...] = (),
) -> ChannelMonetizationSnapshot:
    by_name = _row_map(response)
    views = _metric(by_name, "views")
    watch_time = _metric(by_name, "estimatedMinutesWatched")
    gained = _metric(by_name, "subscribersGained")
    lost = _metric(by_name, "subscribersLost")
    if gained.status == "VALUE" and lost.status == "VALUE":
        subscribers_delta = MetricValue(status="VALUE", value=gained.value - lost.value)
    else:
        subscribers_delta = MetricValue(status="UNAVAILABLE", reason="subscriber_components_not_returned")

    estimated_revenue = _metric(by_name, "estimatedRevenue", reason="monetary_metric_not_authorized_or_not_returned")
    cpm = _metric(by_name, "cpm", reason="monetary_metric_not_authorized_or_not_returned")
    monetized = _metric(by_name, "monetizedPlaybacks", reason="monetary_metric_not_authorized_or_not_returned")
    rpm = MetricValue(status="UNAVAILABLE", reason="requires_estimatedRevenue_and_views")
    if estimated_revenue.status == "VALUE" and views.status == "VALUE" and views.value:
        rpm = MetricValue(status="DERIVED", value=(float(estimated_revenue.value) / float(views.value)) * 1000.0)

    timestamp = retrieved_at or datetime.now(timezone.utc).isoformat()
    evidence = ({
        "source": "youtube_analytics_api_v2",
        "metrics_requested": (*CORE_METRICS, *MONETARY_METRICS),
        "metrics_returned": tuple(sorted(by_name)),
        "retrieved_at": timestamp,
    },)
    combined_limitations = list(limitations)
    for label, metric in (
        ("estimated_revenue", estimated_revenue),
        ("cpm", cpm),
        ("monetized_playbacks", monetized),
    ):
        if metric.status == "UNAVAILABLE":
            combined_limitations.append(f"{label}:{metric.reason}")

    return ChannelMonetizationSnapshot(
        timestamp=timestamp,
        period={"start_date": start_date, "end_date": end_date},
        currency=currency,
        views=views,
        watch_time=watch_time,
        subscribers_delta=subscribers_delta,
        estimated_revenue=estimated_revenue,
        rpm_if_available=rpm,
        cpm_if_available=cpm,
        monetized_playbacks_if_available=monetized,
        top_videos=top_videos,
        revenue_by_video_if_available=revenue_by_video,
        traffic_summary=traffic_summary,
        data_source="youtube_analytics_api_v2",
        data_freshness=timestamp,
        evidence=evidence,
        limitations=tuple(dict.fromkeys(combined_limitations)),
    )


def execute_monetization_observability_capability(
    capability: Any,
    payload: dict[str, Any],
    *,
    service_factory: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    if getattr(capability, "capability_id", None) != MONETIZATION_CAPABILITY_ID:
        raise PermissionError("monetization capability mismatch")
    if getattr(capability, "executor_binding", None) != MONETIZATION_EXECUTOR_BINDING:
        raise PermissionError("monetization executor binding mismatch")
    start_date = payload.get("start_date")
    end_date = payload.get("end_date")
    if not isinstance(start_date, str) or not isinstance(end_date, str):
        raise ValueError("start_date and end_date are required")

    response = payload.get("api_response")
    if response is None:
        if service_factory is None:
            raise RuntimeError("YouTube Analytics service is required for live monetization observation")
        credentials = payload.get("credentials")
        service = service_factory(credentials)
        response = service.reports().query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics=",".join((*CORE_METRICS, *MONETARY_METRICS)),
        ).execute()
    if not isinstance(response, dict):
        raise RuntimeError("YouTube Analytics returned an invalid monetization response")
    return normalize_monetization_snapshot(
        response,
        start_date=start_date,
        end_date=end_date,
        currency=payload.get("currency"),
        limitations=tuple(payload.get("limitations") or ()),
    ).to_dict()
