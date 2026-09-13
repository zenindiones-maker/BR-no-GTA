from __future__ import annotations

from datetime import datetime, timezone

from app.services.gta6_monitor_apscheduler_adapter import APSchedulerGTA6MonitorAdapter
from app.services.gta6_monitor_schedule import GTA6MonitorSchedule
from app.services.gta6_monitor_scheduler import GTA6MonitorScheduler
from app.services.gta6_scheduler_observability import GTA6SchedulerObservability


def emit_gta6_monitor_harness_trigger() -> dict[str, object]:
    """Emit passive evidence only; scheduler never executes MasterAgent sovereignty."""
    return {
        "status": "trigger_emitted",
        "target": "deepseek_harness",
        "requested_capability": "agent:gta6_master",
        "requested_action": "MONITOR",
        "emitted_at": datetime.now(timezone.utc).isoformat(),
    }


def create_gta6_monitor_scheduler(*, schedule: GTA6MonitorSchedule | None = None) -> GTA6MonitorScheduler:
    selected_schedule = schedule or GTA6MonitorSchedule()
    if not isinstance(selected_schedule, GTA6MonitorSchedule):
        raise ValueError("schedule must be a GTA6MonitorSchedule")
    observability = GTA6SchedulerObservability()
    executor = emit_gta6_monitor_harness_trigger
    adapter = APSchedulerGTA6MonitorAdapter(schedule=selected_schedule, executor=executor, observability=observability)
    return GTA6MonitorScheduler(schedule=selected_schedule, executor=executor, adapter=adapter)
