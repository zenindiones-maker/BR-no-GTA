from __future__ import annotations

import json
from pathlib import Path

from scripts.youtube_platform_foundation_live_canary import (
    REQUIRED_MONETARY_SCOPES,
    REQUIRED_PLATFORM_SCOPES,
    inspect_secret_file_isolation,
    inspect_token_scope_profile,
    reduce_block1_certification_status,
    run_live_certification,
)


def test_missing_readonly_tokens_are_explicit_external_configuration_blockers(tmp_path: Path):
    result = run_live_certification(
        read_token_file=tmp_path / "missing-read.json",
        monetary_token_file=tmp_path / "missing-money.json",
        database_file=tmp_path / "control.db",
    )
    assert result["status"] == "EXTERNAL_CONFIGURATION_REQUIRED"
    assert result["gates"]["YOUTUBE_OAUTH_BROKER"] == "EXTERNAL_CONFIGURATION_REQUIRED"
    assert result["gates"]["YOUTUBE_DATA_API_READ"] == "EXTERNAL_CONFIGURATION_REQUIRED"
    assert result["gates"]["YOUTUBE_ANALYTICS_READ"] == "EXTERNAL_CONFIGURATION_REQUIRED"
    assert result["gates"]["YOUTUBE_REPORTING"] == "EXTERNAL_CONFIGURATION_REQUIRED"
    assert result["gates"]["YOUTUBE_MONETARY_ANALYTICS"] == "EXTERNAL_CONFIGURATION_REQUIRED"


def test_scope_profile_requires_exact_readonly_capability_scopes(tmp_path: Path):
    read = tmp_path / "read.json"
    read.write_text(json.dumps({"scopes": list(REQUIRED_PLATFORM_SCOPES)}), encoding="utf-8")
    assert inspect_token_scope_profile(read, REQUIRED_PLATFORM_SCOPES)["status"] == "PASS"

    broad = tmp_path / "broad.json"
    broad.write_text(json.dumps({
        "scopes": [
            *REQUIRED_PLATFORM_SCOPES,
            "https://www.googleapis.com/auth/youtube.upload",
        ]
    }), encoding="utf-8")
    result = inspect_token_scope_profile(broad, REQUIRED_PLATFORM_SCOPES)
    assert result["status"] == "FAIL"
    assert result["reason"] == "WRITE_CAPABLE_SCOPE_PRESENT"


def test_monetary_scope_profile_is_separate_from_non_monetary_read_profile(tmp_path: Path):
    token = tmp_path / "money.json"
    token.write_text(json.dumps({"scopes": list(REQUIRED_MONETARY_SCOPES)}), encoding="utf-8")
    result = inspect_token_scope_profile(token, REQUIRED_MONETARY_SCOPES)
    assert result["status"] == "PASS"
    assert "https://www.googleapis.com/auth/yt-analytics.readonly" not in REQUIRED_MONETARY_SCOPES
    assert "https://www.googleapis.com/auth/yt-analytics-monetary.readonly" in REQUIRED_MONETARY_SCOPES



def test_secret_file_isolation_requires_mode_0600(tmp_path: Path):
    token = tmp_path / "token.json"
    token.write_text("{}", encoding="utf-8")
    token.chmod(0o644)
    failed = inspect_secret_file_isolation(token)
    assert failed["status"] == "FAIL"
    assert failed["reason"] == "TOKEN_FILE_MODE_NOT_0600"

    token.chmod(0o600)
    passed = inspect_secret_file_isolation(token)
    assert passed["status"] == "PASS"



def test_certification_reducer_requires_all_blocking_gates_but_allows_nonblocking_no_eligible_data():
    from scripts.youtube_platform_foundation_live_canary import BLOCKING_GATES

    gates = {key: "PASS" for key in BLOCKING_GATES}
    gates["YOUTUBE_RETENTION_QUERY"] = "NO_ELIGIBLE_DATA"
    assert reduce_block1_certification_status(gates) == "PASS"

    gates["REAL_OWNED_CHANNEL_METADATA"] = "NO_ELIGIBLE_DATA"
    assert reduce_block1_certification_status(gates) == "NOT_YET_PROVEN"

    gates["REAL_OWNED_CHANNEL_METADATA"] = "PASS"
    gates["YOUTUBE_REPORTING_INGESTION_BACKFILL"] = "NO_ELIGIBLE_DATA"
    assert reduce_block1_certification_status(gates) == "NOT_YET_PROVEN"

    gates["YOUTUBE_REPORTING_INGESTION_BACKFILL"] = "PASS"
    gates["YOUTUBE_OAUTH_BROKER"] = "EXTERNAL_CONFIGURATION_REQUIRED"
    assert reduce_block1_certification_status(gates) == "EXTERNAL_CONFIGURATION_REQUIRED"

    gates["YOUTUBE_OAUTH_BROKER"] = "FAIL"
    assert reduce_block1_certification_status(gates) == "FAIL"
