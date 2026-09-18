from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Iterable

RUN_CLASSES=("COLD_RUN","WARM_RETRY")
HISTORY_VERSION="operational-efficiency-history/v1"


class OperationalEfficiencyHistoryError(ValueError):
    pass


def _finite(value: Any, label: str) -> float:
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise OperationalEfficiencyHistoryError(f"{label} must be numeric")
    number=float(value)
    if not math.isfinite(number) or number<0:
        raise OperationalEfficiencyHistoryError(f"{label} must be finite and non-negative")
    return number


def normalize_observation(observation: dict[str,Any]) -> dict[str,Any]:
    if not isinstance(observation,dict):
        raise OperationalEfficiencyHistoryError("observation must be an object")
    run_class=str(observation.get("run_class") or "")
    if run_class not in RUN_CLASSES:
        raise OperationalEfficiencyHistoryError("run_class must be COLD_RUN or WARM_RETRY")
    capability=str(observation.get("capability_id") or "")
    stage=str(observation.get("stage") or "")
    if not capability or not stage:
        raise OperationalEfficiencyHistoryError("capability_id and stage are required")
    wall=_finite(observation.get("wall_clock_seconds",observation.get("elapsed_seconds")),"wall_clock_seconds")
    row=dict(observation)
    row["run_class"]=run_class
    row["capability_id"]=capability
    row["stage"]=stage
    row["wall_clock_seconds"]=wall
    return row


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise OperationalEfficiencyHistoryError("cannot summarize empty values")
    ordered=sorted(values)
    if len(ordered)==1:
        return ordered[0]
    rank=(len(ordered)-1)*percentile
    low=int(math.floor(rank))
    high=int(math.ceil(rank))
    if low==high:
        return ordered[low]
    fraction=rank-low
    return ordered[low]+(ordered[high]-ordered[low])*fraction


def summarize_history(observations: Iterable[dict[str,Any]]) -> list[dict[str,Any]]:
    groups: dict[tuple[str,str,str],list[float]]={}
    for raw in observations:
        row=normalize_observation(raw)
        key=(row["run_class"],row["capability_id"],row["stage"])
        groups.setdefault(key,[]).append(row["wall_clock_seconds"])
    result=[]
    for (run_class,capability,stage),values in sorted(groups.items()):
        result.append({
            "run_class":run_class,
            "capability_id":capability,
            "stage":stage,
            "samples":len(values),
            "p50_wall_clock_seconds":round(_percentile(values,0.50),6),
            "p95_wall_clock_seconds":round(_percentile(values,0.95),6),
            "min_wall_clock_seconds":round(min(values),6),
            "max_wall_clock_seconds":round(max(values),6),
        })
    return result


def append_observation(history: dict[str,Any] | None, observation: dict[str,Any], *, max_samples: int=500) -> dict[str,Any]:
    row=normalize_observation(observation)
    data=deepcopy(history or {"version":HISTORY_VERSION,"observations":[]})
    if data.get("version")!=HISTORY_VERSION:
        raise OperationalEfficiencyHistoryError("history version mismatch")
    observations=list(data.get("observations") or [])
    observations.append(row)
    if len(observations)>max_samples:
        observations=observations[-max_samples:]
    data["observations"]=observations
    data["baselines"]=summarize_history(observations)
    return data
