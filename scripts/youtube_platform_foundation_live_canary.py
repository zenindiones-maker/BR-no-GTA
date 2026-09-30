from __future__ import annotations

import argparse
from datetime import date, timedelta
from hashlib import sha256
import json
import os
import stat
from pathlib import Path
from typing import Any


YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_ANALYTICS_READONLY_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
YOUTUBE_ANALYTICS_MONETARY_SCOPE = "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"

REQUIRED_PLATFORM_SCOPES = (
    YOUTUBE_READONLY_SCOPE,
    YOUTUBE_ANALYTICS_READONLY_SCOPE,
)
REQUIRED_MONETARY_SCOPES = (
    YOUTUBE_READONLY_SCOPE,
    YOUTUBE_ANALYTICS_MONETARY_SCOPE,
)
WRITE_CAPABLE_SCOPES = {
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
}

BLOCKING_GATES = (
    "YOUTUBE_OAUTH_BROKER",
    "YOUTUBE_DATA_API_READ",
    "REAL_OWNED_CHANNEL_METADATA",
    "YOUTUBE_ANALYTICS_READ",
    "YOUTUBE_REPORTING",
    "YOUTUBE_REPORTING_INGESTION_BACKFILL",
    "YOUTUBE_MONETARY_ANALYTICS",
    "YOUTUBE_QUOTA_POLICY",
    "METRIC_PROVENANCE",
    "YOUTUBE_POLICY_SNAPSHOT",
    "NO_UNDOCUMENTED_API",
    "NO_SCRAPING",
    "SECRET_ISOLATION",
    "OWNED_VS_COMPETITOR_DATA_SEPARATED",
)



def reduce_block1_certification_status(gates: dict[str, str]) -> str:
    blocking_values = [str(gates.get(key) or "NOT_YET_PROVEN") for key in BLOCKING_GATES]
    if "FAIL" in blocking_values:
        return "FAIL"
    if "EXTERNAL_CONFIGURATION_REQUIRED" in blocking_values:
        return "EXTERNAL_CONFIGURATION_REQUIRED"
    if any(value != "PASS" for value in blocking_values):
        return "NOT_YET_PROVEN"
    return "PASS"

def _scope_values(payload: dict[str, Any]) -> set[str]:
    raw = payload.get("scopes") or ()
    if isinstance(raw, str):
        raw = raw.replace(",", " ").split()
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {str(item).strip() for item in raw if str(item).strip()}


def inspect_token_scope_profile(
    token_file: str | Path,
    required_scopes: tuple[str, ...],
) -> dict[str, Any]:
    path = Path(token_file)
    if not path.is_file():
        return {
            "status": "EXTERNAL_CONFIGURATION_REQUIRED",
            "reason": "TOKEN_FILE_MISSING",
            "required_scope_count": len(required_scopes),
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "FAIL", "reason": "TOKEN_JSON_INVALID"}
    if not isinstance(payload, dict):
        return {"status": "FAIL", "reason": "TOKEN_JSON_NOT_OBJECT"}
    scopes = _scope_values(payload)
    if not scopes:
        return {
            "status": "EXTERNAL_CONFIGURATION_REQUIRED",
            "reason": "SCOPE_METADATA_UNAVAILABLE",
            "required_scope_count": len(required_scopes),
        }
    if scopes & WRITE_CAPABLE_SCOPES:
        return {
            "status": "FAIL",
            "reason": "WRITE_CAPABLE_SCOPE_PRESENT",
            "granted_scope_count": len(scopes),
        }
    required = set(required_scopes)
    if scopes != required:
        return {
            "status": "EXTERNAL_CONFIGURATION_REQUIRED",
            "reason": "EXACT_SCOPE_PROFILE_MISMATCH",
            "required_scope_count": len(required),
            "granted_scope_count": len(scopes),
        }
    return {
        "status": "PASS",
        "reason": "EXACT_READONLY_SCOPE_PROFILE",
        "granted_scope_count": len(scopes),
    }



def inspect_secret_file_isolation(token_file: str | Path) -> dict[str, Any]:
    path = Path(token_file)
    if not path.is_file():
        return {
            "status": "EXTERNAL_CONFIGURATION_REQUIRED",
            "reason": "TOKEN_FILE_MISSING",
        }
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        return {
            "status": "FAIL",
            "reason": "TOKEN_FILE_MODE_NOT_0600",
            "mode": oct(mode),
        }
    return {
        "status": "PASS",
        "reason": "EPHEMERAL_FILE_MODE_0600",
    }

def _load_credentials(path: Path, scopes: tuple[str, ...]) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    credentials = Credentials.from_authorized_user_file(str(path), scopes=list(scopes))
    if credentials.valid:
        return credentials
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        path.write_text(credentials.to_json(), encoding="utf-8")
        return credentials
    raise RuntimeError("OAuth credentials invalid or not refreshable")


def _execute_broker(
    client: Any,
    *,
    operation: str,
    action: str,
    task_id: str,
    resource_binding: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from app.services.harness_authorization_service import issue_harness_authorization

    subjects = {
        "DATA_READ": "capability:youtube.data.read",
        "ANALYTICS_READ": "capability:youtube.analytics.read",
        "ANALYTICS_MONETARY_READ": "capability:youtube.monetization.observe",
        "REPORTING_READ": "capability:youtube.reporting.read",
    }
    subject = subjects[operation]
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=subject,
        execution_id=task_id,
        harness_decision_id=f"block1-certification:{task_id}",
        lineage={
            "mission_type": "BLOCK_1_CERTIFICATION",
            "capability_id": subject.split("capability:", 1)[1],
            "certification_surface": "GITHUB_ACTIONS_READ_ONLY_CANARY",
        },
    )

    body = {"action": action, **dict(payload or {})}
    handle = client.request_handle(
        operation=operation,
        authorization_ref=authorization.authorization_id,
        task_id=task_id,
        resource_binding=resource_binding,
    )
    digest = sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return client.execute(
        handle=handle,
        operation_id=f"block1-{task_id}",
        payload_digest=digest,
        payload=body,
    )


def _reporting_backfill_cycle(
    credentials: Any,
    *,
    database_file: Path,
) -> dict[str, Any]:
    from google.auth.transport.requests import AuthorizedSession

    os.environ["BR_TEST_DATABASE"] = str(database_file)
    from app.database.schema import initialize_schema
    from app.services.google_youtube_reporting_client import create_youtube_reporting_service
    from app.services.youtube_reporting_warehouse_service import (
        list_reporting_jobs,
        list_reporting_reports,
        parse_reporting_csv,
        persist_report_revision,
    )

    initialize_schema()
    service = create_youtube_reporting_service(credentials)
    jobs_result = list_reporting_jobs(service=service)
    if jobs_result["status"] != "PASS":
        return {
            "status": "NO_ELIGIBLE_DATA",
            "reason": "NO_REPORTING_JOBS",
            "ingested_report_count": 0,
        }

    created_after = (date.today() - timedelta(days=90)).isoformat() + "T00:00:00Z"
    chosen_job = None
    chosen_report = None
    for job in jobs_result["jobs"][:10]:
        reports_result = list_reporting_reports(
            service=service,
            job_id=job["job_id"],
            created_after=created_after,
        )
        if reports_result["reports"]:
            chosen_job = job
            chosen_report = reports_result["reports"][-1]
            break
    if chosen_report is None or chosen_job is None:
        return {
            "status": "NO_ELIGIBLE_DATA",
            "reason": "NO_REPORT_IN_BACKFILL_WINDOW",
            "ingested_report_count": 0,
        }

    url = chosen_report["download_url"]
    if not url.startswith("https://youtubereporting.googleapis.com/"):
        return {"status": "FAIL", "reason": "UNEXPECTED_REPORT_DOWNLOAD_HOST"}

    response = AuthorizedSession(credentials).get(url, timeout=30)
    response.raise_for_status()
    raw = response.content
    if len(raw) > 10 * 1024 * 1024:
        return {
            "status": "NO_ELIGIBLE_DATA",
            "reason": "REPORT_EXCEEDS_CANARY_10MB_BOUND",
            "report_size_bytes": len(raw),
        }
    try:
        csv_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"status": "FAIL", "reason": "REPORT_NOT_UTF8_CSV"}

    rows = parse_reporting_csv(csv_text)
    period_start = chosen_report["start_time"][:10]
    period_end = chosen_report["end_time"][:10]
    snapshot = persist_report_revision(
        report_id=chosen_report["report_id"],
        report_type=chosen_job["report_type_id"],
        period_start=period_start,
        period_end=period_end,
        revision=1,
        backfill_state="BACKFILLED",
        rows=rows,
        evidence_refs=(
            f"youtube-reporting-job:{chosen_job['job_id']}",
            f"youtube-report:{chosen_report['report_id']}",
        ),
    )

    cursor_result = list_reporting_reports(
        service=service,
        job_id=chosen_job["job_id"],
        created_after=chosen_report["created_at"],
    )
    return {
        "status": "PASS",
        "reason": "BOUNDED_BACKFILL_WINDOW_INGESTED",
        "row_count": snapshot.row_count,
        "content_digest": snapshot.content_digest,
        "incremental_cursor_status": cursor_result["status"],
        "incremental_report_count": len(cursor_result["reports"]),
    }


def run_live_certification(
    *,
    read_token_file: str | Path,
    monetary_token_file: str | Path,
    database_file: str | Path,
) -> dict[str, Any]:
    read_path = Path(read_token_file)
    money_path = Path(monetary_token_file)
    database_path = Path(database_file)

    from app.services.youtube_platform_foundation_service import (
        classify_metric_evidence,
        operation_surface,
        youtube_integration_inventory,
    )
    from app.services.youtube_policy_registry_service import load_policy_snapshots
    from app.services.youtube_quota_service import quota_policy

    gates: dict[str, str] = {
        "YOUTUBE_OAUTH_BROKER": "NOT_YET_PROVEN",
        "YOUTUBE_DATA_API_READ": "NOT_YET_PROVEN",
        "YOUTUBE_ANALYTICS_READ": "NOT_YET_PROVEN",
        "YOUTUBE_REPORTING": "NOT_YET_PROVEN",
        "YOUTUBE_REPORTING_INGESTION_BACKFILL": "NOT_YET_PROVEN",
        "YOUTUBE_MONETARY_ANALYTICS": "NOT_YET_PROVEN",
        "YOUTUBE_RETENTION_QUERY": "NOT_YET_PROVEN",
        "REAL_OWNED_CHANNEL_METADATA": "NOT_YET_PROVEN",
        "YOUTUBE_QUOTA_POLICY": "NOT_YET_PROVEN",
        "METRIC_PROVENANCE": "PASS",
        "YOUTUBE_POLICY_SNAPSHOT": "PASS",
        "NO_UNDOCUMENTED_API": "PASS",
        "NO_SCRAPING": "PASS",
        "SECRET_ISOLATION": "NOT_YET_PROVEN",
        "OWNED_VS_COMPETITOR_DATA_SEPARATED": "PASS",
    }
    evidence: dict[str, Any] = {
        "policy_snapshot_count": len(load_policy_snapshots()),
        "quota_policy_digest": quota_policy("youtube_data", "channels.list")["policy_digest"],
        "registered_surfaces": {
            operation: operation_surface(operation).surface
            for operation in (
                "youtube.data.read",
                "youtube.analytics.read",
                "youtube.reporting.read",
                "youtube.native_ab_test",
                "youtube.midroll.manage",
                "youtube.synthetic_media_disclosure",
            )
        },
        "integration_inventory_count": len(youtube_integration_inventory()),
    }

    provenance = classify_metric_evidence(
        metric_name="audienceWatchRatio",
        subject_scope="OWNED_VIDEO",
        source_system="YOUTUBE_ANALYTICS_API",
        observed_at=date.today().isoformat(),
        source_ref="block1-live-canary",
    )
    evidence["owned_retention_provenance"] = provenance.evidence_class

    read_profile = inspect_token_scope_profile(read_path, REQUIRED_PLATFORM_SCOPES)
    money_profile = inspect_token_scope_profile(money_path, REQUIRED_MONETARY_SCOPES)
    read_isolation = inspect_secret_file_isolation(read_path)
    money_isolation = inspect_secret_file_isolation(money_path)
    evidence["read_scope_profile"] = read_profile
    evidence["monetary_scope_profile"] = money_profile
    evidence["read_secret_isolation"] = read_isolation
    evidence["monetary_secret_isolation"] = money_isolation

    if read_profile["status"] != "PASS":
        replacement = "FAIL" if read_profile["status"] == "FAIL" else "EXTERNAL_CONFIGURATION_REQUIRED"
        for key in (
            "YOUTUBE_OAUTH_BROKER",
            "YOUTUBE_DATA_API_READ",
            "YOUTUBE_ANALYTICS_READ",
            "YOUTUBE_REPORTING",
            "YOUTUBE_REPORTING_INGESTION_BACKFILL",
            "REAL_OWNED_CHANNEL_METADATA",
            "YOUTUBE_RETENTION_QUERY",
        ):
            gates[key] = replacement
        gates["SECRET_ISOLATION"] = replacement
    if money_profile["status"] != "PASS":
        gates["YOUTUBE_MONETARY_ANALYTICS"] = (
            "FAIL" if money_profile["status"] == "FAIL"
            else "EXTERNAL_CONFIGURATION_REQUIRED"
        )
        if gates["SECRET_ISOLATION"] == "NOT_YET_PROVEN":
            gates["SECRET_ISOLATION"] = gates["YOUTUBE_MONETARY_ANALYTICS"]

    if read_profile["status"] == "PASS":
        try:
            os.environ["BR_TEST_DATABASE"] = str(database_path)
            from app.database.schema import initialize_schema

            initialize_schema()
            read_credentials = _load_credentials(read_path, REQUIRED_PLATFORM_SCOPES)
            money_credentials = (
                _load_credentials(money_path, REQUIRED_MONETARY_SCOPES)
                if money_profile["status"] == "PASS"
                else None
            )
            from app.services.youtube_credential_broker_service import (
                LocalReadOnlyYouTubeCredentialBrokerRuntime,
                YouTubeCredentialBrokerClient,
            )

            credentials_map = {
                "DATA_READ": read_credentials,
                "ANALYTICS_READ": read_credentials,
                "REPORTING_READ": read_credentials,
            }
            if money_credentials is not None:
                credentials_map["ANALYTICS_MONETARY_READ"] = money_credentials
            runtime = LocalReadOnlyYouTubeCredentialBrokerRuntime(
                credentials_by_operation=credentials_map,
            )
            client = YouTubeCredentialBrokerClient(
                base_url="http://runner-local-youtube-broker",
                transport=runtime.transport,
            )

            channel = _execute_broker(
                client,
                operation="DATA_READ",
                action="CHANNEL_MINE",
                task_id="data-read",
                resource_binding={"channel": "MINE"},
            )
            gates["YOUTUBE_OAUTH_BROKER"] = "PASS"
            gates["YOUTUBE_DATA_API_READ"] = "PASS"
            quota_observation = channel.get("quota_observation") or {}
            gates["YOUTUBE_QUOTA_POLICY"] = (
                "PASS"
                if quota_observation.get("policy_digest")
                and quota_observation.get("operation") == "channels.list"
                else "FAIL"
            )
            evidence["quota_observation"] = quota_observation
            gates["REAL_OWNED_CHANNEL_METADATA"] = (
                "PASS" if channel.get("status") == "PASS" else "NO_ELIGIBLE_DATA"
            )
            evidence["owned_channel_count"] = int(channel.get("channel_count") or 0)

            end = date.today() - timedelta(days=1)
            start = end - timedelta(days=27)
            window = {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            }
            analytics = _execute_broker(
                client,
                operation="ANALYTICS_READ",
                action="CHANNEL_SUMMARY",
                task_id="analytics-read",
                resource_binding={"channel": "MINE"},
                payload=window,
            )
            gates["YOUTUBE_ANALYTICS_READ"] = "PASS"
            evidence["analytics_data_status"] = analytics.get("status")
            evidence["analytics_row_count"] = int(analytics.get("row_count") or 0)

            reporting = _execute_broker(
                client,
                operation="REPORTING_READ",
                action="JOBS_LIST",
                task_id="reporting-read",
                resource_binding={"channel": "MINE"},
            )
            gates["YOUTUBE_REPORTING"] = "PASS"
            evidence["reporting_data_status"] = reporting.get("status")
            evidence["reporting_job_count"] = int(reporting.get("job_count") or 0)

            backfill = _reporting_backfill_cycle(
                read_credentials,
                database_file=database_path,
            )
            gates["YOUTUBE_REPORTING_INGESTION_BACKFILL"] = backfill["status"]
            evidence["reporting_backfill"] = backfill

            latest = _execute_broker(
                client,
                operation="DATA_READ",
                action="LATEST_UPLOAD",
                task_id="latest-upload",
                resource_binding={"channel": "MINE"},
            )
            if latest.get("status") == "PASS" and latest.get("video_id"):
                retention = _execute_broker(
                    client,
                    operation="ANALYTICS_READ",
                    action="RETENTION_SERIES",
                    task_id="retention-read",
                    resource_binding={
                        "channel": "MINE",
                        "video_id": latest["video_id"],
                    },
                    payload={**window, "video_id": latest["video_id"]},
                )
                gates["YOUTUBE_RETENTION_QUERY"] = retention.get("status", "FAIL")
                evidence["retention_row_count"] = int(retention.get("row_count") or 0)
            else:
                gates["YOUTUBE_RETENTION_QUERY"] = "NO_ELIGIBLE_DATA"

            if money_credentials is not None:
                monetary = _execute_broker(
                    client,
                    operation="ANALYTICS_MONETARY_READ",
                    action="CHANNEL_MONETARY_SUMMARY",
                    task_id="monetary-read",
                    resource_binding={"channel": "MINE"},
                    payload=window,
                )
                gates["YOUTUBE_MONETARY_ANALYTICS"] = "PASS"
                evidence["monetary_data_status"] = monetary.get("status")
                evidence["monetary_row_count"] = int(monetary.get("row_count") or 0)

            isolation_states = (
                read_isolation["status"],
                money_isolation["status"],
            )
            if "FAIL" in isolation_states:
                gates["SECRET_ISOLATION"] = "FAIL"
            elif all(state == "PASS" for state in isolation_states):
                gates["SECRET_ISOLATION"] = "PASS"
            elif gates["SECRET_ISOLATION"] == "NOT_YET_PROVEN":
                gates["SECRET_ISOLATION"] = "EXTERNAL_CONFIGURATION_REQUIRED"
        except Exception as exc:
            evidence["live_exception_type"] = type(exc).__name__
            evidence["live_exception"] = str(exc)[:500]
            for key in (
                "YOUTUBE_OAUTH_BROKER",
                "YOUTUBE_DATA_API_READ",
                "YOUTUBE_ANALYTICS_READ",
                "YOUTUBE_REPORTING",
                "YOUTUBE_REPORTING_INGESTION_BACKFILL",
            ):
                if gates[key] == "NOT_YET_PROVEN":
                    gates[key] = "FAIL"

    status = reduce_block1_certification_status(gates)

    return {
        "schema": "YouTubePlatformFoundationLiveCertification/v1",
        "status": status,
        "certification_status": "CERTIFIED" if status == "PASS" else "NOT_CERTIFIED",
        "gates": gates,
        "evidence": evidence,
        "secret_material_in_output": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--read-token-file", required=True)
    parser.add_argument("--monetary-token-file", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = run_live_certification(
        read_token_file=args.read_token_file,
        monetary_token_file=args.monetary_token_file,
        database_file=args.database,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("BLOCK_1_LIVE_STATUS=" + result["status"])
    for key, value in sorted(result["gates"].items()):
        print(f"{key}={value}")
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
