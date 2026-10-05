from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


class BudgetBlocked(RuntimeError):
    pass


class ProjectBindingError(RuntimeError):
    pass


class AwsLifecycleError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkstationSpec:
    project: str
    instance_id: str
    region: str
    budget_name: str
    budget_action_id: str
    account_id: str


class AwsLifecycle:
    def __init__(self, *, ec2: Any, budgets: Any, ssm: Any):
        self.ec2 = ec2
        self.budgets = budgets
        self.ssm = ssm

    def _instance(self, spec: WorkstationSpec) -> dict:
        try:
            response = self.ec2.describe_instances(InstanceIds=[spec.instance_id])
            instance = response["Reservations"][0]["Instances"][0]
        except Exception as exc:
            raise AwsLifecycleError("BLOCKED_AWS_AUTH_OR_API") from exc

        tags = {
            str(row.get("Key") or ""): str(row.get("Value") or "")
            for row in instance.get("Tags", [])
        }
        if tags.get("Project") != spec.project:
            raise ProjectBindingError("BLOCKED_ISOLATION:PROJECT_TAG_MISMATCH")
        return instance

    def status(self, spec: WorkstationSpec) -> str:
        return str(self._instance(spec).get("State", {}).get("Name") or "unknown")

    def _assert_budget_ready(self, spec: WorkstationSpec) -> None:
        try:
            budget_response = self.budgets.describe_budget(
                AccountId=spec.account_id,
                BudgetName=spec.budget_name,
            )
            budget = budget_response["Budget"]
            limit_amount = Decimal(str(budget["BudgetLimit"]["Amount"]))
            actual_amount = Decimal(
                str(
                    budget.get("CalculatedSpend", {})
                    .get("ActualSpend", {})
                    .get("Amount", "0")
                )
            )
            action_response = self.budgets.describe_budget_action(
                AccountId=spec.account_id,
                BudgetName=spec.budget_name,
                ActionId=spec.budget_action_id,
            )
            action = action_response["Action"]
        except Exception as exc:
            raise BudgetBlocked("BLOCKED_BUDGET_POLICY:BUDGET_OR_ACTION_MISSING") from exc

        if limit_amount <= 0 or actual_amount >= limit_amount:
            raise BudgetBlocked("BLOCKED_BUDGET_POLICY:MONTHLY_LIMIT_REACHED")

        if (
            action.get("ActionType") != "RUN_SSM_DOCUMENTS"
            or action.get("ApprovalModel") != "AUTOMATIC"
            or action.get("Status") != "STANDBY"
        ):
            raise BudgetBlocked("BLOCKED_BUDGET_POLICY:STOP_ACTION_NOT_READY")

    def start(self, spec: WorkstationSpec) -> str:
        self._assert_budget_ready(spec)
        state = self.status(spec)
        if state == "running":
            return state
        if state != "stopped":
            raise AwsLifecycleError(f"BLOCKED_INSTANCE_STATE:{state}")

        try:
            self.ec2.start_instances(InstanceIds=[spec.instance_id])
            self.ec2.get_waiter("instance_running").wait(
                InstanceIds=[spec.instance_id]
            )
        except Exception as exc:
            raise AwsLifecycleError("BLOCKED_AWS_AUTH_OR_API") from exc
        return self.status(spec)

    def stop(self, spec: WorkstationSpec) -> str:
        state = self.status(spec)
        if state == "stopped":
            return state
        if state not in {"running", "pending"}:
            raise AwsLifecycleError(f"BLOCKED_INSTANCE_STATE:{state}")

        try:
            self.ec2.stop_instances(InstanceIds=[spec.instance_id])
            self.ec2.get_waiter("instance_stopped").wait(
                InstanceIds=[spec.instance_id]
            )
        except Exception as exc:
            raise AwsLifecycleError("BLOCKED_AWS_AUTH_OR_API") from exc
        return self.status(spec)

    def connect_ready(self, spec: WorkstationSpec) -> bool:
        if self.status(spec) != "running":
            return False
        try:
            response = self.ssm.describe_instance_information(
                Filters=[
                    {
                        "Key": "InstanceIds",
                        "Values": [spec.instance_id],
                    }
                ]
            )
        except Exception as exc:
            raise AwsLifecycleError("BLOCKED_AWS_AUTH_OR_API") from exc

        return any(
            row.get("InstanceId") == spec.instance_id
            and row.get("PingStatus") == "Online"
            for row in response.get("InstanceInformationList", [])
        )
