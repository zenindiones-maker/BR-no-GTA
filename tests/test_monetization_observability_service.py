from types import SimpleNamespace

import pytest

from app.services import monetization_observability_service as svc


def response_with(headers, values):
    return {
        "columnHeaders": [{"name": name} for name in headers],
        "rows": [values],
    }


def cap():
    return SimpleNamespace(
        capability_id=svc.MONETIZATION_CAPABILITY_ID,
        executor_binding=svc.MONETIZATION_EXECUTOR_BINDING,
    )


def test_snapshot_preserves_available_money_metrics_and_derives_rpm():
    response = response_with(
        [
            "views",
            "estimatedMinutesWatched",
            "subscribersGained",
            "subscribersLost",
            "estimatedRevenue",
            "cpm",
            "monetizedPlaybacks",
        ],
        [10000, 42000, 70, 5, 125.0, 8.5, 6000],
    )
    snapshot = svc.normalize_monetization_snapshot(
        response,
        start_date="2026-09-01",
        end_date="2026-09-15",
        currency="USD",
        retrieved_at="2026-09-16T00:00:00+00:00",
    )
    data = snapshot.to_dict()
    assert data["views"] == {"status": "VALUE", "value": 10000, "reason": None}
    assert data["subscribers_delta"]["value"] == 65
    assert data["estimated_revenue"]["value"] == 125.0
    assert data["rpm_if_available"]["status"] == "DERIVED"
    assert data["rpm_if_available"]["value"] == pytest.approx(12.5)
    assert data["cpm_if_available"]["value"] == 8.5
    assert data["monetized_playbacks_if_available"]["value"] == 6000
    assert data["data_source"] == "youtube_analytics_api_v2"
    assert data["evidence"][0]["source"] == "youtube_analytics_api_v2"


def test_missing_monetary_metrics_degrade_explicitly_without_invention():
    response = response_with(
        ["views", "estimatedMinutesWatched", "subscribersGained", "subscribersLost"],
        [400, 1200, 3, 1],
    )
    data = svc.normalize_monetization_snapshot(
        response,
        start_date="2026-09-01",
        end_date="2026-09-15",
    ).to_dict()
    assert data["estimated_revenue"]["status"] == "UNAVAILABLE"
    assert data["estimated_revenue"]["value"] is None
    assert data["rpm_if_available"]["status"] == "UNAVAILABLE"
    assert data["cpm_if_available"]["status"] == "UNAVAILABLE"
    assert data["monetized_playbacks_if_available"]["status"] == "UNAVAILABLE"
    assert any(item.startswith("estimated_revenue:") for item in data["limitations"])


def test_executor_accepts_normalized_api_response_without_credentials_in_result():
    result = svc.execute_monetization_observability_capability(
        cap(),
        {
            "start_date": "2026-09-01",
            "end_date": "2026-09-02",
            "credentials": "SUPER-SECRET-SHOULD-NOT-LEAK",
            "api_response": response_with(["views"], [10]),
        },
    )
    assert "SUPER-SECRET-SHOULD-NOT-LEAK" not in repr(result)
    assert result["views"]["value"] == 10


def test_executor_rejects_wrong_capability_or_binding():
    with pytest.raises(PermissionError):
        svc.execute_monetization_observability_capability(
            SimpleNamespace(capability_id="evil", executor_binding=svc.MONETIZATION_EXECUTOR_BINDING),
            {"start_date": "2026-09-01", "end_date": "2026-09-02", "api_response": {}},
        )
    with pytest.raises(PermissionError):
        svc.execute_monetization_observability_capability(
            SimpleNamespace(capability_id=svc.MONETIZATION_CAPABILITY_ID, executor_binding="evil"),
            {"start_date": "2026-09-01", "end_date": "2026-09-02", "api_response": {}},
        )


def test_monetary_scope_is_read_only():
    assert svc.YOUTUBE_ANALYTICS_MONETARY_SCOPE.endswith("yt-analytics-monetary.readonly")
