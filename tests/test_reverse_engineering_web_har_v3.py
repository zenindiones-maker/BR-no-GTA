from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.reverse_engineering_media_service import ObservationError
from app.services.reverse_engineering_web_har_service import analyze_web_har
from app.services.reverse_engineering_harness_service import (
    WEB_HAR_CAPABILITY_ID, execute_authorized_web_har_observation,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import issue_harness_authorization, revoke_harness_authorization
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request


SECRET = "PRIVATE_BEARER_PASSWORD_1234"


def _har(tmp_path: Path):
    path = tmp_path / "replay.har"
    doc = {
        "log": {
            "version": "1.2",
            "creator": {"name": "Playwright"},
            "entries": [
                {
                    "request": {
                        "method": "GET",
                        "url": "https://example.com/private/SECRET_URL?token=" + SECRET,
                        "headers": [{"name": "Authorization", "value": "Bearer " + SECRET}],
                        "cookies": [{"name": "session", "value": SECRET}],
                    },
                    "response": {
                        "status": 200,
                        "content": {"mimeType": "text/html", "text": SECRET},
                        "headers": [{"name": "Set-Cookie", "value": SECRET}],
                    },
                    "time": 110.0,
                },
                {
                    "request": {"method": "POST", "url": "https://api.example.com/v1/user?key=" + SECRET, "postData": {"text": SECRET}},
                    "response": {"status": 500, "content": {"mimeType": "application/json", "text": SECRET}},
                    "time": 400.0,
                },
            ],
        },
    }
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _decision():
    return route_harness_request(HarnessRoutingRequest(
        intent="Read local allowed HAR without executing browser or exposing headers",
        authorized_action="RESEARCH",
        domain="website-observation",
        required_capability_id=WEB_HAR_CAPABILITY_ID,
        fallback_allowed=False, provider_required=False, learning_required=False,
    ))


def _authorization(tmp_path):
    return issue_harness_authorization(
        authorized_action="RESEARCH", subject=f"capability:{WEB_HAR_CAPABILITY_ID}",
        lineage={"allowed_media_roots": [str(tmp_path)]},
    )


def test_har_sanitizes_credentials_and_requires_local_evidence(tmp_path):
    report = analyze_web_har(_har(tmp_path), rights="owned")
    text = json.dumps(report, ensure_ascii=False)
    assert SECRET not in text
    assert "example.com" not in text
    assert "SECRET_URL" not in text
    assert "/private/" not in text
    assert "Authorization" not in text
    assert report["request_count"] == 2
    assert report["unique_origin_count"] == 2
    assert report["methods"] == {"GET": 1, "POST": 1}
    assert report["response_status_families"] == {"2xx": 1, "5xx": 1}
    assert report["mime_families"] == {"html": 1, "json": 1}
    assert report["response_time_p95_ms"] == 400
    assert report["network_access"] == "NONE"
    assert report["auth_headers_released"] is False
    assert len(report["evidence_sha256"]) == 64


def test_har_is_routed_by_actual_persisted_harness_authorization(tmp_path):
    target = _har(tmp_path)
    record = GLOBAL_CAPABILITY_REGISTRY.get(WEB_HAR_CAPABILITY_ID)
    assert record is not None and record.execution_enabled
    assert record.authority == record.publication_authority == record.memory_write == "NONE"
    decision = _decision()
    auth = _authorization(tmp_path)
    result = CapabilityAdapter().execute(
        authorization=auth,
        task_envelope=TaskEnvelope(
            task_id="offline-har-test",
            capability_id=WEB_HAR_CAPABILITY_ID,
            action="RESEARCH", objective="Observe owned HAR behavior offline",
        ),
        routing_decision=decision,
        payload={"source_path": str(target), "rights": "owned"},
    )
    assert result.result["status"] == "MEASURED"
    assert result.result["evidence"]["request_count"] == 2
    assert SECRET not in json.dumps(result.to_dict())
    assert result.result["production_mutation"] is False


def test_replayed_or_fabricated_harness_authorization_cannot_read_har(tmp_path):
    target = _har(tmp_path)
    d = _decision()
    a = _authorization(tmp_path)
    revoke_harness_authorization(a)
    for invalid in (a, "fake-auth-id"):
        with pytest.raises(PermissionError):
            execute_authorized_web_har_observation(
                authorization=invalid, routing_decision=d,
                payload={"source_path": str(target), "rights": "owned"},
            )


def test_har_blocked_without_rights_and_on_bad_schema(tmp_path):
    path = _har(tmp_path)
    with pytest.raises(ObservationError, match="WEB_HAR_RIGHTS_REQUIRED"):
        analyze_web_har(path, rights="guess")
    path.write_text('{"log":{"entries":[],"version":"1.1"}}')
    with pytest.raises(ObservationError, match="WEB_HAR_INVALID_SCHEMA"):
        analyze_web_har(path, rights="owned")


def test_har_cannot_escape_allowed_root(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    target = _har(other)
    auth = _authorization(approved)
    with pytest.raises(PermissionError, match="OUTSIDE_HARNESS_SCOPE"):
        execute_authorized_web_har_observation(
            authorization=auth, routing_decision=_decision(),
            payload={"source_path": str(target), "rights": "owned"},
        )


def test_har_rejects_non_http_and_bad_status(tmp_path):
    path = _har(tmp_path)
    obj = json.loads(path.read_text())
    obj["log"]["entries"][0]["request"]["url"] = "file:///etc/passwd"
    path.write_text(json.dumps(obj))
    with pytest.raises(ObservationError, match="WEB_HAR_URL_INVALID"):
        analyze_web_har(path, rights="owned")
    obj["log"]["entries"][0]["request"]["url"] = "https://example.org"
    obj["log"]["entries"][0]["response"]["status"] = -1
    path.write_text(json.dumps(obj))
    with pytest.raises(ObservationError, match="WEB_HAR_STATUS_INVALID"):
        analyze_web_har(path, rights="owned")
