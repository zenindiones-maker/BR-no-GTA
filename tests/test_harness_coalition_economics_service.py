from __future__ import annotations

from app.services.harness_coalition_economics_service import (
    CoalitionExecutionEconomics,
    evaluate_multi_agent_value_delta,
)


def test_economics_records_coordination_tax_and_reuse():
    e = CoalitionExecutionEconomics(
        mission_id="m1",
        task_id="t1",
        single_agent_estimated_cost=100.0,
        selected_coalition_size=3,
        spawned_subagents=2,
        semantic_calls=4,
        tool_calls=12,
        input_tokens=1000,
        output_tokens=500,
        context_bytes=90000,
        wall_clock_ms=8000,
        provider_cost=0.25,
        coordination_messages=6,
        duplicate_work_units=1,
        reused_work_units=3,
        failed_specialist_work_units=0,
        fan_in_cost=15.0,
        verified_result=True,
        robustness_benefit=True,
    )
    assert e.coordination_tax() > 0
    assert e.reuse_ratio() == 0.75


def test_larger_equivalent_coalition_without_value_is_regression():
    result = evaluate_multi_agent_value_delta(
        champion={
            "verified_result": True,
            "wall_clock_ms": 5000,
            "provider_cost": 0.1,
            "selected_coalition_size": 1,
            "critical_regressions": 0,
        },
        challenger={
            "verified_result": True,
            "wall_clock_ms": 9000,
            "provider_cost": 0.4,
            "selected_coalition_size": 4,
            "critical_regressions": 0,
            "robustness_benefit": False,
        },
    )
    assert result["multi_agent_helped"] is False
    assert result["verdict"] == "REGRESSION"


def test_larger_coalition_can_be_accepted_when_verified_robustness_improves():
    result = evaluate_multi_agent_value_delta(
        champion={
            "verified_result": True,
            "wall_clock_ms": 8000,
            "provider_cost": 0.2,
            "selected_coalition_size": 1,
            "critical_regressions": 0,
        },
        challenger={
            "verified_result": True,
            "wall_clock_ms": 8500,
            "provider_cost": 0.22,
            "selected_coalition_size": 3,
            "critical_regressions": 0,
            "robustness_benefit": True,
        },
    )
    assert result["multi_agent_helped"] is True
    assert result["verdict"] == "VALUE_PROVEN"


def test_critical_regression_always_blocks_value_claim():
    result = evaluate_multi_agent_value_delta(
        champion={"verified_result": True, "wall_clock_ms": 10000, "provider_cost": 1.0, "selected_coalition_size": 1, "critical_regressions": 0},
        challenger={"verified_result": True, "wall_clock_ms": 1000, "provider_cost": 0.01, "selected_coalition_size": 2, "critical_regressions": 1, "robustness_benefit": True},
    )
    assert result["verdict"] == "HARD_REGRESSION"
    assert result["multi_agent_helped"] is False
