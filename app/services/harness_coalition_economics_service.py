from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CoalitionExecutionEconomics:
    mission_id: str
    task_id: str
    single_agent_estimated_cost: float
    selected_coalition_size: int
    spawned_subagents: int
    semantic_calls: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    context_bytes: int
    wall_clock_ms: int
    provider_cost: float
    coordination_messages: int
    duplicate_work_units: int
    reused_work_units: int
    failed_specialist_work_units: int
    fan_in_cost: float
    verified_result: bool
    robustness_benefit: bool
    schema: str = "CoalitionExecutionEconomics/v1"

    def coordination_tax(self) -> float:
        return (
            float(self.spawned_subagents)
            + float(self.coordination_messages)
            + float(self.duplicate_work_units)
            + float(self.failed_specialist_work_units)
            + float(self.fan_in_cost)
        )

    def reuse_ratio(self) -> float:
        denom = self.reused_work_units + self.duplicate_work_units
        if denom <= 0:
            return 0.0
        return float(self.reused_work_units) / float(denom)


def evaluate_multi_agent_value_delta(
    *,
    champion: dict[str, Any],
    challenger: dict[str, Any],
) -> dict[str, Any]:
    if int(challenger.get("critical_regressions") or 0) > int(
        champion.get("critical_regressions") or 0
    ):
        return {
            "multi_agent_helped": False,
            "verdict": "HARD_REGRESSION",
            "reason": "critical_regressions_increased",
        }

    champion_ok = bool(champion.get("verified_result"))
    challenger_ok = bool(challenger.get("verified_result"))
    if not challenger_ok:
        return {
            "multi_agent_helped": False,
            "verdict": "REGRESSION",
            "reason": "challenger_result_not_verified",
        }
    if challenger_ok and not champion_ok:
        return {
            "multi_agent_helped": True,
            "verdict": "VALUE_PROVEN",
            "reason": "verified_success_where_champion_failed",
        }

    ch_wall = float(champion.get("wall_clock_ms") or 0)
    ca_wall = float(challenger.get("wall_clock_ms") or 0)
    ch_cost = float(champion.get("provider_cost") or 0)
    ca_cost = float(challenger.get("provider_cost") or 0)
    ch_size = int(champion.get("selected_coalition_size") or 1)
    ca_size = int(challenger.get("selected_coalition_size") or 1)
    robustness = bool(challenger.get("robustness_benefit"))

    strictly_more_expensive = (
        ca_size > ch_size
        and ca_wall >= ch_wall
        and ca_cost >= ch_cost
    )
    if strictly_more_expensive and not robustness:
        return {
            "multi_agent_helped": False,
            "verdict": "REGRESSION",
            "reason": "larger_coalition_without_verified_value",
        }

    efficiency_improved = (
        ca_wall < ch_wall
        or ca_cost < ch_cost
        or ca_size < ch_size
    )
    helped = bool(robustness or efficiency_improved)
    return {
        "multi_agent_helped": helped,
        "verdict": "VALUE_PROVEN" if helped else "NO_VALUE_DELTA",
        "reason": (
            "verified_robustness_or_efficiency_gain"
            if helped
            else "no_measurable_multi_agent_advantage"
        ),
    }
