#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import boto3


REGION = "sa-east-1"
PROJECTS = {
    "hazewave": {
        "budget_name": "hazewave-media-workstation-monthly",
    },
    "br-no-gta": {
        "budget_name": "br-no-gta-media-workstation-monthly",
    },
}
COMMANDS = ("START", "STATUS", "CONNECT_READY", "STOP")


class ControlBlocked(RuntimeError):
    pass


def approved_budget() -> float:
    raw = os.environ.get("MONTHLY_BUDGET_USD", "").strip()
    if not raw:
        raise ControlBlocked("MONTHLY_BUDGET_USD_UNSET")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ControlBlocked("BLOCKED_BUDGET_POLICY") from exc
    if value <= 0:
        raise ControlBlocked("BLOCKED_BUDGET_POLICY")
    return value


def find_instance(ec2, project: str) -> str:
    response = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Project", "Values": [project]},
            {"Name": "tag:Purpose", "Values": ["persistent-media-workstation"]},
            {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
        ]
    )
    ids = [
        item["InstanceId"]
        for reservation in response.get("Reservations", [])
        for item in reservation.get("Instances", [])
    ]
    if len(ids) != 1:
        raise ControlBlocked(f"BLOCKED_INSTANCE_IDENTITY:count={len(ids)}")
    return ids[0]


def instance_status(ec2, instance_id: str) -> dict:
    response = ec2.describe_instance_status(
        InstanceIds=[instance_id],
        IncludeAllInstances=True,
    )
    rows = response.get("InstanceStatuses", [])
    if not rows:
        # A stopped instance may be omitted transiently; describe_instances is the fallback.
        desc = ec2.describe_instances(InstanceIds=[instance_id])
        inst = desc["Reservations"][0]["Instances"][0]
        return {
            "instance_id": instance_id,
            "state": inst["State"]["Name"],
            "system_status": "NOT_APPLICABLE",
            "instance_status": "NOT_APPLICABLE",
        }
    row = rows[0]
    return {
        "instance_id": instance_id,
        "state": row["InstanceState"]["Name"],
        "system_status": row.get("SystemStatus", {}).get("Status", "unknown"),
        "instance_status": row.get("InstanceStatus", {}).get("Status", "unknown"),
    }


def require_budget_action(sts, budgets, project: str) -> None:
    expected = approved_budget()
    account = sts.get_caller_identity()["Account"]
    budget_name = PROJECTS[project]["budget_name"]
    budget = budgets.describe_budget(AccountId=account, BudgetName=budget_name)["Budget"]
    observed = float(budget["BudgetLimit"]["Amount"])
    if abs(observed - expected) > 0.0001:
        raise ControlBlocked(
            f"BLOCKED_BUDGET_POLICY:expected={expected:g}:observed={observed:g}"
        )
    actions = budgets.describe_budget_actions_for_budget(
        AccountId=account,
        BudgetName=budget_name,
        MaxResults=100,
    ).get("Actions", [])
    ready = any(
        action.get("ActionType") == "RUN_SSM_DOCUMENTS"
        and action.get("ApprovalModel") == "AUTOMATIC"
        for action in actions
    )
    if not ready:
        raise ControlBlocked("BLOCKED_BUDGET_POLICY:AUTOMATIC_STOP_ACTION_MISSING")


def ssm_online(ssm, instance_id: str) -> bool:
    rows = ssm.describe_instance_information(
        Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]
    ).get("InstanceInformationList", [])
    return bool(rows) and rows[0].get("PingStatus") == "Online"


def run_connect_ready_proof(ssm, instance_id: str) -> dict:
    response = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": ["/usr/local/bin/workstation-connect-ready-proof"]},
        TimeoutSeconds=120,
    )
    command_id = response["Command"]["CommandId"]
    deadline = time.monotonic() + 130
    while time.monotonic() < deadline:
        try:
            inv = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id,
            )
        except ssm.exceptions.InvocationDoesNotExist:
            time.sleep(2)
            continue
        status = inv.get("Status")
        if status in {"Pending", "InProgress", "Delayed"}:
            time.sleep(2)
            continue
        if status != "Success":
            raise ControlBlocked(
                "BLOCKED_STREAMING:"
                + status
                + ":"
                + inv.get("StandardErrorContent", "")[-500:]
            )
        stdout = inv.get("StandardOutputContent", "")
        if "CONNECT_READY=PASS" not in stdout:
            raise ControlBlocked("BLOCKED_STREAMING:CONNECT_READY_PROOF_MISSING")
        return {"status": status, "output": stdout.strip()}
    raise ControlBlocked("BLOCKED_STREAMING:CONNECT_READY_TIMEOUT")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", choices=sorted(PROJECTS))
    parser.add_argument("command", type=str.upper, choices=COMMANDS)
    args = parser.parse_args()

    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2", region_name=REGION)
    ssm = session.client("ssm", region_name=REGION)
    sts = session.client("sts", region_name=REGION)
    budgets = session.client("budgets", region_name="us-east-1")

    try:
        instance_id = find_instance(ec2, args.project)
        before = instance_status(ec2, instance_id)

        if args.command == "STATUS":
            result = before

        elif args.command == "START":
            require_budget_action(sts, budgets, args.project)
            if before["state"] == "stopped":
                ec2.start_instances(InstanceIds=[instance_id])
                ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id])
            result = instance_status(ec2, instance_id)

        elif args.command == "STOP":
            if before["state"] not in {"stopped", "stopping"}:
                ec2.stop_instances(InstanceIds=[instance_id])
                ec2.get_waiter("instance_stopped").wait(InstanceIds=[instance_id])
            result = instance_status(ec2, instance_id)

        elif args.command == "CONNECT_READY":
            if before["state"] != "running":
                raise ControlBlocked("BLOCKED_STREAMING:INSTANCE_NOT_RUNNING")
            if not ssm_online(ssm, instance_id):
                raise ControlBlocked("BLOCKED_AWS_AUTH_OR_SSM:SSM_OFFLINE")
            result = {
                **before,
                "connect_ready": run_connect_ready_proof(ssm, instance_id),
            }

        else:
            raise ControlBlocked("BLOCKED_UNKNOWN_COMMAND")

    except Exception as exc:
        if isinstance(exc, ControlBlocked):
            status = str(exc).split(":", 1)[0]
            detail = str(exc)
        else:
            status = "BLOCKED_AWS_AUTH_OR_API"
            detail = type(exc).__name__
        print(json.dumps({
            "schema": "WorkstationLifecycleResult/v1",
            "project": args.project,
            "command": args.command,
            "status": status,
            "detail": detail,
        }, sort_keys=True))
        return 2

    print(json.dumps({
        "schema": "WorkstationLifecycleResult/v1",
        "project": args.project,
        "command": args.command,
        "status": "PASS",
        "result": result,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
