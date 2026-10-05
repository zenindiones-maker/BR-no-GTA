#!/usr/bin/env python3
from __future__ import annotations

import json
import time

import boto3


REGION = "sa-east-1"
PROJECTS = ("hazewave", "br-no-gta")


def find_instance(ec2, project: str) -> str:
    response = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Project", "Values": [project]},
            {"Name": "tag:Purpose", "Values": ["persistent-media-workstation"]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )
    ids = [
        instance["InstanceId"]
        for reservation in response.get("Reservations", [])
        for instance in reservation.get("Instances", [])
    ]
    if len(ids) != 1:
        raise RuntimeError(f"BLOCKED_ISOLATION:INSTANCE_COUNT:{project}:{len(ids)}")
    return ids[0]


def command_for_bucket(bucket: str) -> str:
    return f"""set +e
out=$(aws s3api list-objects-v2 --bucket {bucket} --max-keys 1 2>&1)
rc=$?
if [ "$rc" -eq 0 ]; then
  echo CROSS_ACCESS_ALLOWED
  exit 42
fi
if printf '%s' "$out" | grep -Eq 'AccessDenied|Forbidden|403'; then
  echo AccessDenied
  exit 13
fi
printf '%s\n' "$out"
exit 14
"""


def probe(ssm, instance_id: str, bucket: str) -> dict:
    command = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [command_for_bucket(bucket)]},
        TimeoutSeconds=90,
    )["Command"]["CommandId"]

    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        try:
            inv = ssm.get_command_invocation(
                CommandId=command,
                InstanceId=instance_id,
            )
        except ssm.exceptions.InvocationDoesNotExist:
            time.sleep(2)
            continue
        if inv.get("Status") in {"Pending", "InProgress", "Delayed"}:
            time.sleep(2)
            continue

        combined = (
            inv.get("StandardOutputContent", "")
            + "\n"
            + inv.get("StandardErrorContent", "")
        )
        if "CROSS_ACCESS_ALLOWED" in combined:
            raise RuntimeError("BLOCKED_ISOLATION:CROSS_ACCESS_ALLOWED")
        if "AccessDenied" not in combined:
            raise RuntimeError("BLOCKED_ISOLATION:DENIAL_UNPROVEN")
        return {
            "instance_id": instance_id,
            "other_bucket": bucket,
            "access": "DENIED",
            "evidence": "AccessDenied",
        }
    raise RuntimeError("BLOCKED_ISOLATION:SSM_TIMEOUT")


def main() -> int:
    session = boto3.Session(region_name=REGION)
    sts = session.client("sts", region_name=REGION)
    ec2 = session.client("ec2", region_name=REGION)
    ssm = session.client("ssm", region_name=REGION)

    try:
        account = sts.get_caller_identity()["Account"]
        buckets = {
            "hazewave": f"cloud-media-hazewave-{account}",
            "br-no-gta": f"cloud-media-br-no-gta-{account}",
        }
        instances = {project: find_instance(ec2, project) for project in PROJECTS}
        results = {
            "hazewave_to_br": probe(
                ssm, instances["hazewave"], buckets["br-no-gta"]
            ),
            "br_to_hazewave": probe(
                ssm, instances["br-no-gta"], buckets["hazewave"]
            ),
        }
    except Exception as exc:
        print("CROSS_PROJECT_STORAGE_ISOLATION=FAIL")
        print(
            json.dumps(
                {
                    "schema": "CrossProjectIsolationEvidence/v1",
                    "status": "BLOCKED_ISOLATION",
                    "detail": str(exc),
                },
                sort_keys=True,
            )
        )
        return 2

    print("CROSS_PROJECT_STORAGE_ISOLATION=PASS")
    print(
        json.dumps(
            {
                "schema": "CrossProjectIsolationEvidence/v1",
                "status": "PASS",
                "results": results,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
