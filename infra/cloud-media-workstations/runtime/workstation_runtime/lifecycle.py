from __future__ import annotations


class BudgetBlocked(RuntimeError):
    pass


class AwsApiError(RuntimeError):
    pass


class LifecycleController:
    def __init__(self, *, ec2, budget):
        self.ec2 = ec2
        self.budget = budget

    def status(self, instance_id: str) -> str:
        try:
            return self.ec2.describe_state(instance_id)
        except Exception as exc:
            raise AwsApiError("BLOCKED_AWS_AUTH_OR_API") from exc

    def start(self, project: str, instance_id: str) -> str:
        if not self.budget.guardrail_ready(project):
            raise BudgetBlocked("BLOCKED_BUDGET_POLICY")
        state = self.status(instance_id)
        if state == "running":
            return state
        if state not in {"stopped", "stopping", "pending"}:
            raise AwsApiError(f"BLOCKED_INSTANCE_STATE:{state}")
        if state == "stopped":
            try:
                self.ec2.start(instance_id)
            except Exception as exc:
                raise AwsApiError("BLOCKED_AWS_AUTH_OR_API") from exc
        return self.status(instance_id)

    def stop(self, project: str, instance_id: str) -> str:
        state = self.status(instance_id)
        if state == "stopped":
            return state
        if state not in {"running", "pending", "stopping"}:
            raise AwsApiError(f"BLOCKED_INSTANCE_STATE:{state}")
        if state != "stopping":
            try:
                self.ec2.stop(instance_id)
            except Exception as exc:
                raise AwsApiError("BLOCKED_AWS_AUTH_OR_API") from exc
        return self.status(instance_id)
