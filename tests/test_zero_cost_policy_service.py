import pytest
from app.services.zero_cost_policy_service import CostClass, ZeroCostFailureReason, ZeroCostPolicyError, assess_zero_cost, enforce_zero_cost

def test_paid_provider_rejected():
    with pytest.raises(ZeroCostPolicyError) as exc: enforce_zero_cost(CostClass.PAID)
    assert exc.value.reason is ZeroCostFailureReason.PAID_PROVIDER_FORBIDDEN

def test_unknown_cost_provider_rejected():
    with pytest.raises(ZeroCostPolicyError) as exc: enforce_zero_cost("unclassified")
    assert exc.value.reason is ZeroCostFailureReason.UNKNOWN_COST_PROVIDER_FORBIDDEN

def test_free_no_billing_allowed():
    assert assess_zero_cost(CostClass.FREE_NO_BILLING).eligible

def test_free_quota_exhaustion_fails_closed():
    assert assess_zero_cost(CostClass.FREE_QUOTA_LIMITED, quota_available=True).eligible
    denied=assess_zero_cost(CostClass.FREE_QUOTA_LIMITED, quota_available=False)
    assert not denied.eligible and denied.reason is ZeroCostFailureReason.FREE_QUOTA_EXHAUSTED
