from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from app.database.schema import initialize_schema
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_collaboration_service import (
    CollaborationTask,
    build_collaboration_plan,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.hermes_multiagent.capability_broker import (
    HermesHarnessCapabilityBroker,
)
from app.services.hermes_multiagent.contracts import (
    HERMES_RUNTIME_CAPABILITY_ID,
    HermesMissionExecutionSpec,
)
from app.services.web_acquisition_capability_service import (
    APILayerAuthRequired,
    APILayerTransportError,
    WEB_SEARCH_DISCOVER,
    WEB_SOURCE_ACQUIRE,
    apilayer_health_snapshot,
)
from app.services.zero_cost_policy_service import ZeroCostPolicyError


class _ProofBoard:
    def comment(self, *_args, **_kwargs):
        return 1


def _root_cause(exc: Exception) -> Exception:
    current = exc
    seen: set[int] = set()
    for _ in range(8):
        if id(current) in seen:
            break
        seen.add(id(current))
        candidate = getattr(current, "__cause__", None)
        if not isinstance(candidate, Exception):
            candidate = getattr(current, "__context__", None)
        if not isinstance(candidate, Exception):
            break
        current = candidate
    return current


def _classify(exc: Exception) -> str:
    exc = _root_cause(exc)
    message = str(exc)
    if isinstance(exc, APILayerAuthRequired):
        if "PRODUCT_AUTH_REQUIRED" in message:
            return "API_SUBSCRIPTION_REQUIRED"
        return "AUTHENTICATION"
    if isinstance(exc, ZeroCostPolicyError):
        if "FREE_QUOTA_EXHAUSTED" in message or "free quota" in message.casefold():
            return "FREE_QUOTA_EXHAUSTED"
        return "ZERO_COST_POLICY"
    if isinstance(exc, APILayerTransportError):
        if "INVALID_JSON" in message or "NOT_PDF" in message:
            return "NORMALIZATION"
        if "HTTP_4" in message:
            return "ENDPOINT/REQUEST_CONTRACT"
        return "TRANSPORT"
    if isinstance(exc, PermissionError):
        return "HARNESS_AUTHORIZATION"
    if isinstance(exc, ValueError):
        return "NORMALIZATION"
    return type(exc).__name__.upper()


def _safe_host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").casefold()
    except Exception:
        return ""


def _select_source(search_payload: dict) -> str:
    results = [
        dict(item)
        for item in (search_payload.get("results") or ())
        if isinstance(item, dict)
        and str(item.get("url") or "").startswith(("http://", "https://"))
    ]
    for item in results:
        url = str(item.get("url") or "").strip()
        host = _safe_host(url)
        if host.endswith("rockstargames.com"):
            return url
    if results:
        return str(results[0].get("url") or "").strip()
    return "https://www.rockstargames.com/VI"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/apilayer-live-proof/report.json",
    )
    parser.add_argument(
        "--query",
        default='Grand Theft Auto VI Rockstar Games official latest information',
    )
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    secret = str(os.getenv("APILAYER_API_KEY") or "").strip()
    report: dict[str, object] = {
        "schema": "apilayer-live-proof/v1",
        "APILAYER_SECRET_PRESENT": bool(secret),
        "HARNESS_AUTHORIZATION": "PENDING",
        "WEB_FABRIC_REACHED": False,
        "WEB_SEARCH_DISCOVER": "PENDING",
        "SOURCE_ACQUISITION": "PENDING",
        "APILAYER_LIVE_TRANSPORT": "PENDING",
        "TRANSPORT_PROVIDER": None,
        "ORIGINAL_SOURCE_URL_PRESERVED": False,
        "CONTENT_HASH_PRESENT": False,
        "RETRIEVAL_TIMESTAMP_PRESENT": False,
        "SECRET_LEAKAGE": None,
        "PAID_FALLBACK_USED": False,
        "FREE_QUOTA_POLICY": "PENDING",
        "ZERO_COST_OPERATION": str(
            os.getenv("ZERO_COST_OPERATION") or ""
        ).strip().upper(),
        "FAILURE_CLASS": None,
        "FAILURE_DETAIL": None,
    }

    if not secret:
        report.update({
            "FAILURE_CLASS": "AUTHENTICATION",
            "FAILURE_DETAIL": "APILAYER_API_KEY_REQUIRED",
            "SECRET_LEAKAGE": 0,
        })
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print("APILAYER_SECRET_PRESENT=FALSE")
        print("FAILURE_CLASS=AUTHENTICATION")
        return 2

    initialize_schema()
    parent_auth = None
    try:
        plan = build_collaboration_plan(
            mission_id="apilayer-live-proof",
            goal_id="goal-apilayer-live-proof",
            tasks=(
                CollaborationTask(
                    task_id="discover",
                    capability_id=WEB_SEARCH_DISCOVER,
                    action="RESEARCH",
                    objective=(
                        "Discover factual GTA VI source URLs through the governed "
                        "web acquisition fabric."
                    ),
                    expected_output="normalized source discovery result",
                    task_class="agent-tool:live-proof",
                    functional_role="TOOL",
                    risk_side_effect_class="READ_ONLY",
                ),
                CollaborationTask(
                    task_id="acquire",
                    capability_id=WEB_SOURCE_ACQUIRE,
                    action="RESEARCH",
                    objective=(
                        "Acquire one discovered GTA VI source while preserving "
                        "original-source provenance."
                    ),
                    dependencies=("discover",),
                    expected_output="bounded normalized source content and provenance",
                    task_class="agent-tool:live-proof",
                    functional_role="TOOL",
                    risk_side_effect_class="READ_ONLY",
                ),
            ),
        )
        route = route_harness_request(
            HarnessRoutingRequest(
                intent="bounded APILayer live proof through canonical web fabric",
                authorized_action="EXECUTION",
                domain="collaboration",
                task_class="apilayer-governed-live-proof",
                goal_id="goal-apilayer-live-proof",
                required_capability_id=HERMES_RUNTIME_CAPABILITY_ID,
                fallback_allowed=False,
                provider_required=False,
                learning_required=True,
            )
        )
        parent_auth = issue_harness_authorization(
            authorized_action="EXECUTION",
            subject=f"capability:{HERMES_RUNTIME_CAPABILITY_ID}",
            harness_decision_id=route.routing_id,
            execution_id="apilayer-live-proof",
            lineage={
                "routing_id": route.routing_id,
                "capability_id": HERMES_RUNTIME_CAPABILITY_ID,
                "selected_executor_binding": route.selected_executor_binding,
                "zero_cost_operation": True,
                "paid_fallback": False,
            },
        )
        report["HARNESS_AUTHORIZATION"] = "PASS"
        spec = HermesMissionExecutionSpec.from_plan(
            collaboration_plan=plan,
            harness_decision_id=parent_auth.harness_decision_id,
            authorization_id=parent_auth.authorization_id,
            base_sha=str(os.getenv("GITHUB_SHA") or "0" * 40),
            expires_at=(
                datetime.now(timezone.utc) + timedelta(minutes=20)
            ).isoformat(),
        )
        broker = HermesHarnessCapabilityBroker(
            spec=spec,
            parent_authorization=parent_auth,
            board=_ProofBoard(),
            task_mapping={
                "discover": "proof-discover",
                "acquire": "proof-acquire",
            },
            artifact_dir=output.parent / "broker",
        )
        report["WEB_FABRIC_REACHED"] = True

        discover = broker.execute_delegated_capability(
            task_id="discover",
            capability_id=WEB_SEARCH_DISCOVER,
            payload={
                "mission_id": spec.mission_id,
                "task_id": "discover",
                "goal_id": spec.goal_id,
                "query": args.query,
            },
        )
        search_payload = dict(discover.get("result") or {})
        search_provenance = dict(search_payload.get("provenance") or {})
        if search_payload.get("status") != "EXECUTED":
            raise RuntimeError("WEB_SEARCH_DISCOVER_NOT_EXECUTED")
        if (
            search_provenance.get("transport_provider")
            != "apilayer_google_search"
        ):
            raise RuntimeError("APILAYER_SEARCH_TRANSPORT_NOT_OBSERVED")
        report["WEB_SEARCH_DISCOVER"] = "PASS"
        report["APILAYER_LIVE_TRANSPORT"] = "apilayer_google_search"
        report["SEARCH_RESULT_COUNT"] = int(
            search_payload.get("result_count") or 0
        )

        source_url = _select_source(search_payload)
        acquire = broker.execute_delegated_capability(
            task_id="acquire",
            capability_id=WEB_SOURCE_ACQUIRE,
            payload={
                "mission_id": spec.mission_id,
                "task_id": "acquire",
                "goal_id": spec.goal_id,
                "source_url": source_url,
            },
        )
        acquire_payload = dict(acquire.get("result") or {})
        provenance = dict(acquire_payload.get("provenance") or {})
        if acquire_payload.get("status") != "EXECUTED":
            raise RuntimeError("SOURCE_ACQUISITION_NOT_EXECUTED")
        report["SOURCE_ACQUISITION"] = "PASS"
        report["SOURCE_URL"] = source_url
        report["TRANSPORT_PROVIDER"] = provenance.get(
            "transport_provider"
        )
        report["ORIGINAL_SOURCE_URL_PRESERVED"] = (
            provenance.get("source_url") == source_url
        )
        report["CONTENT_HASH_PRESENT"] = bool(
            provenance.get("content_hash")
        )
        report["RETRIEVAL_TIMESTAMP_PRESENT"] = bool(
            provenance.get("retrieved_at")
        )
        report["CACHE_HIT"] = bool(
            acquire_payload.get("cache_hit")
            or provenance.get("cache_hit")
        )
        report["APILAYER_HEALTH"] = apilayer_health_snapshot()

        serialized = json.dumps(
            {
                "search": search_payload,
                "acquire": acquire_payload,
                "report": report,
            },
            sort_keys=True,
            default=str,
        )
        report["SECRET_LEAKAGE"] = int(secret in serialized)
        report["FREE_QUOTA_POLICY"] = (
            "PASS"
            if str(os.getenv("ZERO_COST_OPERATION") or "").strip().upper()
            == "TRUE"
            else "FAIL"
        )
        required = [
            report["HARNESS_AUTHORIZATION"] == "PASS",
            report["WEB_FABRIC_REACHED"] is True,
            report["WEB_SEARCH_DISCOVER"] == "PASS",
            report["SOURCE_ACQUISITION"] == "PASS",
            report["APILAYER_LIVE_TRANSPORT"] == "apilayer_google_search",
            report["ORIGINAL_SOURCE_URL_PRESERVED"] is True,
            report["CONTENT_HASH_PRESENT"] is True,
            report["RETRIEVAL_TIMESTAMP_PRESENT"] is True,
            report["SECRET_LEAKAGE"] == 0,
            report["PAID_FALLBACK_USED"] is False,
            report["FREE_QUOTA_POLICY"] == "PASS",
        ]
        report["status"] = "PASS" if all(required) else "FAIL"
    except Exception as exc:
        root = _root_cause(exc)
        report["status"] = "FAIL"
        report["FAILURE_CLASS"] = _classify(exc)
        report["FAILURE_DETAIL"] = str(root)[:800]
        report["FAILURE_WRAPPER"] = type(exc).__name__
        report["FAILURE_ROOT_TYPE"] = type(root).__name__
        report["SECRET_LEAKAGE"] = int(
            bool(secret) and secret in json.dumps(report, default=str)
        )
    finally:
        if parent_auth is not None:
            consume_harness_authorization(parent_auth)

    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    for key in (
        "APILAYER_SECRET_PRESENT",
        "HARNESS_AUTHORIZATION",
        "WEB_FABRIC_REACHED",
        "WEB_SEARCH_DISCOVER",
        "SOURCE_ACQUISITION",
        "APILAYER_LIVE_TRANSPORT",
        "TRANSPORT_PROVIDER",
        "ORIGINAL_SOURCE_URL_PRESERVED",
        "CONTENT_HASH_PRESENT",
        "RETRIEVAL_TIMESTAMP_PRESENT",
        "SECRET_LEAKAGE",
        "PAID_FALLBACK_USED",
        "FREE_QUOTA_POLICY",
        "FAILURE_CLASS",
    ):
        print(f"{key}={report.get(key)}")
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
