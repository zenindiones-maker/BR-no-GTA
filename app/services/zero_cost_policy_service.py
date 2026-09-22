from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

ZERO_COST_OPERATION = True

class CostClass(str, Enum):
    FREE_NO_BILLING = "FREE_NO_BILLING"
    FREE_QUOTA_LIMITED = "FREE_QUOTA_LIMITED"
    FREE_ENDPOINT = "FREE_ENDPOINT"
    PAID = "PAID"
    UNKNOWN_COST = "UNKNOWN_COST"

class ZeroCostFailureReason(str, Enum):
    ZERO_COST_POLICY_BLOCKED = "ZERO_COST_POLICY_BLOCKED"
    FREE_QUOTA_EXHAUSTED = "FREE_QUOTA_EXHAUSTED"
    PAID_PROVIDER_FORBIDDEN = "PAID_PROVIDER_FORBIDDEN"
    UNKNOWN_COST_PROVIDER_FORBIDDEN = "UNKNOWN_COST_PROVIDER_FORBIDDEN"

@dataclass(frozen=True)
class ZeroCostAssessment:
    eligible: bool
    cost_class: CostClass
    reason: ZeroCostFailureReason | None
    quota_available: bool | None

class ZeroCostPolicyError(RuntimeError):
    def __init__(self, reason: ZeroCostFailureReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason

def normalize_cost_class(value: str | CostClass | None) -> CostClass:
    if isinstance(value, CostClass):
        return value
    try:
        return CostClass(str(value or "").strip().upper())
    except ValueError:
        return CostClass.UNKNOWN_COST

def assess_zero_cost(cost_class: str | CostClass | None, *, quota_available: bool | None = None) -> ZeroCostAssessment:
    resolved = normalize_cost_class(cost_class)
    if resolved is CostClass.FREE_NO_BILLING:
        return ZeroCostAssessment(True, resolved, None, quota_available)
    if resolved in {CostClass.FREE_QUOTA_LIMITED, CostClass.FREE_ENDPOINT}:
        if quota_available is False:
            return ZeroCostAssessment(False, resolved, ZeroCostFailureReason.FREE_QUOTA_EXHAUSTED, quota_available)
        return ZeroCostAssessment(True, resolved, None, quota_available)
    if resolved is CostClass.PAID:
        return ZeroCostAssessment(False, resolved, ZeroCostFailureReason.PAID_PROVIDER_FORBIDDEN, quota_available)
    return ZeroCostAssessment(False, CostClass.UNKNOWN_COST, ZeroCostFailureReason.UNKNOWN_COST_PROVIDER_FORBIDDEN, quota_available)

def enforce_zero_cost(cost_class: str | CostClass | None, *, quota_available: bool | None = None) -> ZeroCostAssessment:
    assessment = assess_zero_cost(cost_class, quota_available=quota_available)
    if not assessment.eligible:
        raise ZeroCostPolicyError(
            assessment.reason or ZeroCostFailureReason.ZERO_COST_POLICY_BLOCKED,
            "Provider is not eligible under ZERO_COST_OPERATION",
        )
    return assessment
