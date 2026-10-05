#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

import boto3

from workstation_runtime.aws_preflight import (
    AwsAuthBlocked,
    GpuQuotaBlocked,
    PreflightConfig,
    run_preflight,
)

REGION = "sa-east-1"
INSTANCE_TYPES = ("g6f.2xlarge", "g6.2xlarge")
PRICE_TERM_CLASS = "AmazonEC2CurrentGeneration"
AWS_PRICE_EVIDENCE = "AWS_PRICE_EVIDENCE"
CAPACITY_WARNING = "AZ_OFFERING_NOT_CAPACITY_GUARANTEE"
CAPACITY_BLOCKER = "BLOCKED_CAPACITY_UNPROVEN"


@dataclass
class Clients:
    sts: object
    quotas: object
    ec2: object
    pricing: object


def parse_budget() -> float | None:
    raw = os.environ.get("MONTHLY_BUDGET_USD", "").strip()
    if not raw:
        return None
    return float(raw)


def safe_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        raise AwsAuthBlocked("BLOCKED_AWS_AUTH_OR_API") from exc


def main() -> int:
    session = boto3.Session(region_name=REGION)
    sts = session.client("sts", region_name=REGION)
    quotas = session.client("service-quotas", region_name=REGION)
    ec2 = session.client("ec2", region_name=REGION)
    pricing = session.client("pricing", region_name="us-east-1")

    # Explicit API surfaces required by the workstation mission.
    try:
        identity = sts.get_caller_identity()
        quota_surface = quotas.list_service_quotas(ServiceCode="ec2")
        offerings = {
            instance_type: ec2.describe_instance_type_offerings(
                LocationType="availability-zone",
                Filters=[{"Name": "instance-type", "Values": [instance_type]}],
            )
            for instance_type in INSTANCE_TYPES
        }
        instance_type_details = ec2.describe_instance_types(
            InstanceTypes=list(INSTANCE_TYPES)
        )
        ebs_modification_surface = ec2.describe_volumes_modifications(MaxResults=5)
    except Exception as exc:
        print(json.dumps({
            "schema": "CloudMediaWorkstationPreflight/v1",
            "status": "BLOCKED_AWS_AUTH",
            "region": REGION,
            "detail": type(exc).__name__,
        }, sort_keys=True))
        return 2

    clients = Clients(sts=sts, quotas=quotas, ec2=ec2, pricing=pricing)
    try:
        result = run_preflight(
            clients=clients,
            config=PreflightConfig(
                region=REGION,
                monthly_budget_usd=parse_budget(),
            ),
        )
    except AwsAuthBlocked as exc:
        print(json.dumps({
            "schema":"CloudMediaWorkstationPreflight/v1",
            "status":"BLOCKED_AWS_AUTH",
            "region":REGION,
            "detail":str(exc),
        }, sort_keys=True))
        return 2
    except GpuQuotaBlocked as exc:
        print(json.dumps({
            "schema":"CloudMediaWorkstationPreflight/v1",
            "status":"BLOCKED_GPU_QUOTA",
            "region":REGION,
            "detail":str(exc),
        }, sort_keys=True))
        return 2
    except Exception as exc:
        print(json.dumps({
            "schema":"CloudMediaWorkstationPreflight/v1",
            "status":"BLOCKED_AWS_AUTH_OR_API",
            "region":REGION,
            "detail":type(exc).__name__,
        }, sort_keys=True))
        return 2

    # Do not confuse AZ offering metadata with allocatable On-Demand capacity.
    result["capacity"]["warning"] = CAPACITY_WARNING
    result["capacity"]["live_launch_capacity"] = CAPACITY_BLOCKER
    result["instance_type_details"] = instance_type_details.get("InstanceTypes", [])
    result["api_surfaces"] = {
        "sts.get_caller_identity": "PASS",
        "service-quotas.list_service_quotas": "PASS",
        "describe_instance_type_offerings": "PASS",
        "describe_instance_types": "PASS",
        "describe_volumes_modifications": "PASS",
    }
    result["pricing_api"] = {
        "service_code": "AmazonEC2",
        "term_class": PRICE_TERM_CLASS,
        "get_products": "PASS",
    }
    result["cost_evidence_schema"] = "CostEvidence/v1"
    result[AWS_PRICE_EVIDENCE] = result["cost_evidence"]
    result["account_safe_reference"] = result["account_safe_reference"]
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
