from __future__ import annotations

import pytest

from workstation_runtime.aws_lifecycle import (
    AwsLifecycle,
    BudgetBlocked,
    ProjectBindingError,
    WorkstationSpec,
)


class FakeWaiter:
    def wait(self, **kwargs):
        return None


class FakeEc2:
    def __init__(self, state="stopped", project="hazewave"):
        self.state = state
        self.project = project
        self.started = 0
        self.stopped = 0

    def describe_instances(self, InstanceIds):
        return {
            "Reservations": [{
                "Instances": [{
                    "InstanceId": InstanceIds[0],
                    "State": {"Name": self.state},
                    "Tags": [{"Key": "Project", "Value": self.project}],
                }]
            }]
        }

    def start_instances(self, InstanceIds):
        self.started += 1
        self.state = "running"

    def stop_instances(self, InstanceIds):
        self.stopped += 1
        self.state = "stopped"

    def get_waiter(self, name):
        return FakeWaiter()


class FakeBudgets:
    def __init__(self, *, actual=10.0, limit=100.0, action_ok=True):
        self.actual = actual
        self.limit = limit
        self.action_ok = action_ok

    def describe_budget(self, **kwargs):
        return {
            "Budget": {
                "BudgetLimit": {"Amount": str(self.limit), "Unit": "USD"},
                "CalculatedSpend": {
                    "ActualSpend": {"Amount": str(self.actual), "Unit": "USD"}
                },
            }
        }

    def describe_budget_action(self, **kwargs):
        if not self.action_ok:
            raise RuntimeError("missing action")
        return {
            "Action": {
                "ActionId": kwargs["ActionId"],
                "ActionType": "RUN_SSM_DOCUMENTS",
                "ApprovalModel": "AUTOMATIC",
                "Status": "STANDBY",
            }
        }


class FakeSsm:
    def __init__(self, online=True):
        self.online = online

    def describe_instance_information(self, Filters):
        return {
            "InstanceInformationList": (
                [{"InstanceId": "i-1", "PingStatus": "Online"}] if self.online else []
            )
        }


SPEC = WorkstationSpec(
    project="hazewave",
    instance_id="i-1",
    region="sa-east-1",
    budget_name="hazewave-media-workstation-monthly",
    budget_action_id="a-1",
    account_id="123456789012",
)


def test_start_is_idempotent_and_budget_guarded() -> None:
    ec2 = FakeEc2()
    ctl = AwsLifecycle(ec2=ec2, budgets=FakeBudgets(), ssm=FakeSsm())
    assert ctl.start(SPEC) == "running"
    assert ctl.start(SPEC) == "running"
    assert ec2.started == 1


def test_stop_is_idempotent_and_never_terminates() -> None:
    ec2 = FakeEc2(state="running")
    ctl = AwsLifecycle(ec2=ec2, budgets=FakeBudgets(), ssm=FakeSsm())
    assert ctl.stop(SPEC) == "stopped"
    assert ctl.stop(SPEC) == "stopped"
    assert ec2.stopped == 1
    assert not hasattr(ec2, "terminate_instances")


def test_start_blocks_when_actual_spend_reaches_budget() -> None:
    ctl = AwsLifecycle(
        ec2=FakeEc2(),
        budgets=FakeBudgets(actual=100.0, limit=100.0),
        ssm=FakeSsm(),
    )
    with pytest.raises(BudgetBlocked, match="BLOCKED_BUDGET_POLICY"):
        ctl.start(SPEC)


def test_start_blocks_without_automatic_budget_action() -> None:
    ctl = AwsLifecycle(
        ec2=FakeEc2(),
        budgets=FakeBudgets(action_ok=False),
        ssm=FakeSsm(),
    )
    with pytest.raises(BudgetBlocked, match="BLOCKED_BUDGET_POLICY"):
        ctl.start(SPEC)


def test_project_tag_binding_prevents_cross_control() -> None:
    ctl = AwsLifecycle(
        ec2=FakeEc2(project="br-no-gta"),
        budgets=FakeBudgets(),
        ssm=FakeSsm(),
    )
    with pytest.raises(ProjectBindingError, match="BLOCKED_ISOLATION"):
        ctl.status(SPEC)


def test_connect_ready_requires_running_and_ssm_online() -> None:
    ctl = AwsLifecycle(
        ec2=FakeEc2(state="running"),
        budgets=FakeBudgets(),
        ssm=FakeSsm(online=True),
    )
    assert ctl.connect_ready(SPEC) is True

    offline = AwsLifecycle(
        ec2=FakeEc2(state="running"),
        budgets=FakeBudgets(),
        ssm=FakeSsm(online=False),
    )
    assert offline.connect_ready(SPEC) is False
