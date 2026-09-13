from app.services.gta6_monitor_apscheduler_adapter import APSchedulerGTA6MonitorAdapter
from app.services.gta6_monitor_schedule import GTA6MonitorSchedule
from app.services.gta6_monitor_scheduler import GTA6MonitorScheduler
from app.services.gta6_monitor_scheduler_factory import create_gta6_monitor_scheduler, emit_gta6_monitor_harness_trigger


def test_factory_creates_scheduler_and_adapter():
    scheduler=create_gta6_monitor_scheduler(); assert isinstance(scheduler,GTA6MonitorScheduler); assert isinstance(scheduler.adapter,APSchedulerGTA6MonitorAdapter)

def test_factory_preserves_schedule():
    schedule=GTA6MonitorSchedule(interval_seconds=120, timeout=30, enabled=False, job_id="test")
    scheduler=create_gta6_monitor_scheduler(schedule=schedule); assert scheduler.schedule is schedule and scheduler.adapter.schedule is schedule

def test_scheduler_emits_trigger_only():
    scheduler=create_gta6_monitor_scheduler(); assert scheduler.adapter.executor is emit_gta6_monitor_harness_trigger
    result=scheduler.run_now(); assert result["status"] == "trigger_emitted"; assert result["target"] == "deepseek_harness"; assert result["requested_capability"] == "agent:gta6_master"
