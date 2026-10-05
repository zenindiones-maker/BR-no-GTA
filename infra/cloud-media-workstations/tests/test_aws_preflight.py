from __future__ import annotations

import json

from workstation_runtime.aws_preflight import (
    PreflightEvidence,
    evaluate_preflight,
    extract_price_dimensions,
    find_gpu_quota,
    safe_account_reference,
    shared_instance_azs,
)


def test_account_reference_is_nonreversible_and_redacted() -> None:
    account = "123456789012"
    ref = safe_account_reference(account)
    assert account not in ref
    assert ref.startswith("sha256:")
    assert len(ref) == len("sha256:") + 16


def test_find_gpu_quota_uses_named_g_and_vt_quota() -> None:
    quotas = [
        {"QuotaName": "Running On-Demand Standard instances", "Value": 100.0},
        {"QuotaName": "Running On-Demand G and VT instances", "Value": 16.0},
    ]
    assert find_gpu_quota(quotas) == 16.0


def test_shared_instance_azs_requires_both_instance_types() -> None:
    offerings = [
        {"InstanceType": "g6f.2xlarge", "Location": "sa-east-1a"},
        {"InstanceType": "g6.2xlarge", "Location": "sa-east-1a"},
        {"InstanceType": "g6.2xlarge", "Location": "sa-east-1b"},
    ]
    assert shared_instance_azs(offerings) == ["sa-east-1a"]


def test_extract_price_dimensions_returns_only_numeric_usd() -> None:
    product = {
        "terms": {
            "OnDemand": {
                "term": {
                    "priceDimensions": {
                        "dim": {
                            "unit": "Hrs",
                            "description": "Linux On Demand",
                            "pricePerUnit": {"USD": "1.2340000000"},
                        }
                    }
                }
            }
        }
    }
    rows = extract_price_dimensions(product)
    assert rows == [
        {
            "unit": "Hrs",
            "description": "Linux On Demand",
            "usd": 1.234,
        }
    ]


def base_evidence() -> PreflightEvidence:
    return PreflightEvidence(
        account_reference="sha256:abc",
        region="sa-east-1",
        gpu_quota_vcpus=16.0,
        required_gpu_vcpus=16,
        shared_azs=("sa-east-1a",),
        instance_hourly_usd={
            "g6f.2xlarge": 1.0,
            "g6.2xlarge": 2.0,
        },
        gp3_usd_per_gb_month=0.1,
        data_transfer_dimensions=(
            {"unit": "GB", "description": "Data transfer out", "usd": 0.1},
        ),
        secret_parameters={
            "hazewave": {
                "tailscale": True,
                "sunshine_username": True,
                "sunshine_password": True,
            },
            "br-no-gta": {
                "tailscale": True,
                "sunshine_username": True,
                "sunshine_password": True,
            },
        },
        monthly_budget_usd=100.0,
        pricing_source="AWS_PRICE_LIST_API",
        capacity_evidence="INSTANCE_TYPE_OFFERING_ONLY",
    )


def test_budget_unset_fails_closed_after_safe_evidence_collection() -> None:
    ev = base_evidence()
    ev = ev.__class__(**{**ev.__dict__, "monthly_budget_usd": None})
    result = evaluate_preflight(ev)
    assert result.overall_status == "BLOCKED_BUDGET_POLICY"
    assert "MONTHLY_BUDGET_USD_UNSET" in result.blockers


def test_gpu_quota_below_required_is_blocker() -> None:
    ev = base_evidence()
    ev = ev.__class__(**{**ev.__dict__, "gpu_quota_vcpus": 8.0})
    result = evaluate_preflight(ev)
    assert result.overall_status == "BLOCKED_GPU_QUOTA"


def test_missing_common_az_is_capacity_blocker() -> None:
    ev = base_evidence()
    ev = ev.__class__(**{**ev.__dict__, "shared_azs": ()})
    result = evaluate_preflight(ev)
    assert result.overall_status == "BLOCKED_CAPACITY"


def test_missing_project_secret_blocks_streaming() -> None:
    ev = base_evidence()
    secrets = json.loads(json.dumps(ev.secret_parameters))
    secrets["hazewave"]["tailscale"] = False
    ev = ev.__class__(**{**ev.__dict__, "secret_parameters": secrets})
    result = evaluate_preflight(ev)
    assert result.overall_status == "BLOCKED_STREAMING"


def test_preflight_never_calls_offering_check_actual_capacity_pass() -> None:
    result = evaluate_preflight(base_evidence())
    assert result.overall_status == "PREFLIGHT_READY_FOR_PROVISIONING"
    assert result.capacity_status == "UNPROVEN_UNTIL_RUN_INSTANCES"


def test_missing_price_evidence_blocks_provisioning() -> None:
    ev = base_evidence()
    ev = ev.__class__(**{**ev.__dict__, "gp3_usd_per_gb_month": None})
    result = evaluate_preflight(ev)
    assert result.overall_status == "BLOCKED_PRICE_EVIDENCE"
