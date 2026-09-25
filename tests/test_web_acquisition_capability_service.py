from __future__ import annotations

import json
from urllib import error

import pytest

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.zero_cost_policy_service import ZeroCostPolicyError
from app.services import web_acquisition_capability_service as web


class FakeResponse:
    def __init__(self, body: bytes, *, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = dict(headers or {})
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def read(self, _limit=-1):
        return self.body


def _route(capability_id, *, action="RESEARCH"):
    return route_harness_request(
        HarnessRoutingRequest(
            intent=f"test {capability_id}",
            authorized_action=action,
            domain="web-acquisition",
            task_class="agent-tool:test",
            required_capability_id=capability_id,
            provider_required=False,
            fallback_allowed=False,
            learning_required=False,
        )
    )


def _auth(route):
    return issue_harness_authorization(
        authorized_action=route.authorized_action,
        subject=f"capability:{route.selected_capability_id}",
        harness_decision_id=route.routing_id,
        execution_id="web-fabric-test",
        lineage={
            "routing_id": route.routing_id,
            "capability_id": route.selected_capability_id,
            "selected_executor_binding": route.selected_executor_binding,
        },
    )


def test_registry_exposes_generic_web_capabilities_without_llm_provider_role():
    for capability_id in (
        web.WEB_SEARCH_DISCOVER,
        web.WEB_SOURCE_ACQUIRE,
        web.WEB_EVIDENCE_SNAPSHOT,
    ):
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        assert record is not None
        assert record.domain == "web-acquisition"
        assert record.capability_type == "CAPABILITY"
        assert record.cost_class == "FREE_QUOTA_LIMITED"
        assert record.fallback_eligibility is False


def test_direct_source_fetch_precedes_apilayer_and_cache_precedes_network(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("BR_WEB_ACQUISITION_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("APILAYER_API_KEY", raising=False)
    calls = []
    def urlopen(req, timeout):
        calls.append((req.full_url, dict(req.header_items())))
        return FakeResponse(
            b"<html>official source</html>",
            headers={"Content-Type": "text/html"},
        )
    monkeypatch.setattr(web.request, "urlopen", urlopen)
    route = _route(web.WEB_SOURCE_ACQUIRE)
    auth = _auth(route)
    first = web.execute_web_source_acquire(
        authorization=auth,
        routing_decision=route,
        payload={"source_url": "https://example.com/news"},
    )
    assert first["provenance"]["transport_provider"] == "direct"
    assert first["provenance"]["source_url"] == "https://example.com/news"
    assert len(calls) == 1

    auth2 = _auth(route)
    second = web.execute_web_source_acquire(
        authorization=auth2,
        routing_decision=route,
        payload={"source_url": "https://example.com/news"},
    )
    assert second["cache_hit"] is True
    assert len(calls) == 1


def test_direct_failure_uses_scraper_lite_exactly_once_and_redacts_secret(
    monkeypatch,
    tmp_path,
):
    secret = "super-secret-apilayer-key"
    monkeypatch.setenv("BR_WEB_ACQUISITION_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("APILAYER_API_KEY", secret)
    calls = []
    def urlopen(req, timeout):
        calls.append(req)
        if len(calls) == 1:
            raise error.URLError("blocked")
        return FakeResponse(
            b"<html>scraped source</html>",
            headers={
                "x-ratelimit-remaining-month": "1499",
                "x-ratelimit-limit-month": "1500",
            },
        )
    monkeypatch.setattr(web.request, "urlopen", urlopen)
    route = _route(web.WEB_SOURCE_ACQUIRE)
    result = web.execute_web_source_acquire(
        authorization=_auth(route),
        routing_decision=route,
        payload={"source_url": "https://example.com/blocked"},
    )
    assert len(calls) == 2
    assert result["provenance"]["transport_provider"] == "apilayer_scraper"
    assert result["provenance"]["source_url"] == "https://example.com/blocked"
    assert secret not in json.dumps(result, sort_keys=True)


def test_search_missing_secret_is_product_scoped_auth_required(monkeypatch):
    monkeypatch.delenv("APILAYER_API_KEY", raising=False)
    route = _route(web.WEB_SEARCH_DISCOVER)
    with pytest.raises(web.APILayerAuthRequired, match="APILAYER_API_KEY_REQUIRED"):
        web.execute_web_search_discover(
            authorization=_auth(route),
            routing_decision=route,
            payload={"query": "GTA 6 Rockstar"},
        )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "APILAYER_AUTHENTICATION_FAILED"),
        (403, "APILAYER_SUBSCRIPTION_REQUIRED"),
    ],
)
def test_apilayer_http_auth_and_subscription_failures_are_distinct(
    monkeypatch,
    status,
    expected,
):
    web._QUOTA_STATE.clear()
    monkeypatch.setenv("APILAYER_API_KEY", "fixture-key")
    monkeypatch.setattr(
        web.request,
        "urlopen",
        lambda *_a, **_k: (_ for _ in ()).throw(
            error.HTTPError(
                "https://api.apilayer.com/google_search",
                status,
                "fixture",
                {},
                None,
            )
        ),
    )
    route = _route(web.WEB_SEARCH_DISCOVER)
    with pytest.raises(web.APILayerAuthRequired, match=expected):
        web.execute_web_search_discover(
            authorization=_auth(route),
            routing_decision=route,
            payload={"query": "GTA 6"},
        )


def test_quota_exhaustion_blocks_apilayer_without_paid_upgrade(monkeypatch):
    web._QUOTA_STATE.clear()
    monkeypatch.setenv("APILAYER_API_KEY", "fixture-key")
    web._QUOTA_STATE["apilayer_google_search"] = {"quota_remaining": 0}
    route = _route(web.WEB_SEARCH_DISCOVER)
    with pytest.raises(ZeroCostPolicyError):
        web.execute_web_search_discover(
            authorization=_auth(route),
            routing_decision=route,
            payload={"query": "GTA 6"},
        )


def test_snapshot_requires_explicit_need_before_network(monkeypatch):
    monkeypatch.setenv("APILAYER_API_KEY", "fixture-key")
    monkeypatch.setattr(
        web.request,
        "urlopen",
        lambda *_a, **_k: pytest.fail("network must not run"),
    )
    route = _route(web.WEB_EVIDENCE_SNAPSHOT)
    with pytest.raises(ValueError, match="snapshot_required=true"):
        web.execute_web_evidence_snapshot(
            authorization=_auth(route),
            routing_decision=route,
            payload={"source_url": "https://example.com/source"},
        )

def test_html_decode_extracts_article_text_before_character_ceiling():
    shell = "<nav><svg>" + ("navigation-noise " * 12000) + "</svg></nav>"
    article = (
        "<article><h1>GTA 6 collector set</h1>"
        "<p>The $400 collector set does not include the game itself.</p>"
        "<p>Rockstar lists the physical contents separately.</p></article>"
    )
    raw = (
        "<!doctype html><html><body>" + shell + article + "</body></html>"
    ).encode()

    decoded = web._decode_source(
        raw,
        content_type="text/html; charset=utf-8",
    )

    assert "The $400 collector set does not include the game itself." in decoded
    assert "Rockstar lists the physical contents separately." in decoded
    assert "navigation-noise" not in decoded
    assert len(decoded) < web.MAX_SOURCE_CHARS
