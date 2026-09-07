import pytest

from app.database.gta6_master_agent_repository import (
    create_gta6_master_agent_run,
    get_gta6_master_agent_run,
    list_gta6_master_agent_runs,
)


def test_create_and_get_gta6_master_agent_run():
    created = create_gta6_master_agent_run(
        execution_id="execution-test-001",
        cycle_number=1,
        action="MONITOR",
        reason="Verificar novas atualizações.",
        priority="MEDIUM",
        confidence=0.95,
        tool="br_gta6_monitor_run_once",
        success=True,
        started_at="2026-09-07T12:00:00+00:00",
        completed_at="2026-09-07T12:00:02+00:00",
        result={
            "changed": False,
            "items_found": 0,
        },
    )

    assert created["id"] > 0
    assert created["execution_id"] == "execution-test-001"
    assert created["cycle_number"] == 1
    assert created["status"] == "COMPLETED"
    assert created["action"] == "MONITOR"
    assert created["reason"] == "Verificar novas atualizações."
    assert created["priority"] == "MEDIUM"
    assert created["confidence"] == 0.95
    assert created["tool"] == "br_gta6_monitor_run_once"
    assert created["success"] is True
    assert created["result"] == {
        "changed": False,
        "items_found": 0,
    }

    loaded = get_gta6_master_agent_run(created["id"])

    assert loaded == created


def test_list_gta6_master_agent_runs_filters_by_execution_id():
    create_gta6_master_agent_run(
        execution_id="execution-test-002",
        cycle_number=1,
        action="RESEARCH",
        reason="Pesquisar novidades.",
        priority="HIGH",
        confidence=0.9,
        tool="br_research_run",
        success=True,
        started_at="2026-09-07T12:01:00+00:00",
        result={"total": 3},
    )

    create_gta6_master_agent_run(
        execution_id="execution-test-003",
        cycle_number=1,
        action="WAIT",
        reason="Nenhuma ação necessária.",
        priority="LOW",
        confidence=0.8,
        tool=None,
        success=True,
        started_at="2026-09-07T12:02:00+00:00",
        result=None,
    )

    runs = list_gta6_master_agent_runs(
        execution_id="execution-test-002",
    )

    assert len(runs) == 1
    assert runs[0]["execution_id"] == "execution-test-002"
    assert runs[0]["action"] == "RESEARCH"


def test_list_gta6_master_agent_runs_filters_by_status():
    create_gta6_master_agent_run(
        execution_id="execution-test-004",
        cycle_number=1,
        action="MONITOR",
        reason="Monitorar.",
        priority="MEDIUM",
        confidence=0.95,
        tool="br_gta6_monitor_run_once",
        success=True,
        started_at="2026-09-07T12:03:00+00:00",
        result={},
        status="COMPLETED",
    )

    runs = list_gta6_master_agent_runs(status="COMPLETED")

    assert runs
    assert all(run["status"] == "COMPLETED" for run in runs)


def test_repository_rejects_non_serializable_result():
    with pytest.raises(ValueError, match="result must be JSON serializable"):
        create_gta6_master_agent_run(
            execution_id="execution-test-005",
            cycle_number=1,
            action="MONITOR",
            reason="Teste.",
            priority="MEDIUM",
            confidence=0.95,
            tool="br_gta6_monitor_run_once",
            success=True,
            started_at="2026-09-07T12:04:00+00:00",
            result={"invalid": object()},
        )


def test_repository_rejects_invalid_cycle_number():
    with pytest.raises(
        ValueError,
        match="cycle_number must be greater than zero",
    ):
        create_gta6_master_agent_run(
            execution_id="execution-test-006",
            cycle_number=0,
            action="MONITOR",
            reason="Teste.",
            priority="MEDIUM",
            confidence=0.95,
            tool="br_gta6_monitor_run_once",
            success=True,
            started_at="2026-09-07T12:05:00+00:00",
            result={},
        )
