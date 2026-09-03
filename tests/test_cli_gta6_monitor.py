from unittest.mock import patch

from app.cli import main


def test_cli_gta6_monitor_run_once_processes_monitor_cycle(
    capsys,
):
    result = {
        "url": "https://www.rockstargames.com/newswire",
        "status_code": 200,
        "change": {
            "changed": True,
        },
        "baseline": False,
        "items_found": 3,
        "items_ingested": 2,
        "items_duplicated": 1,
        "knowledge_ids": [10, 11, 12],
    }

    with patch(
        "sys.argv",
        ["br-no-gta", "gta6-monitor", "run-once"],
    ), patch(
        "app.cli.run_gta6_monitor_once",
        return_value=result,
    ) as run_monitor:
        main()

    run_monitor.assert_called_once_with()

    captured = capsys.readouterr()

    assert "Monitor GTA6 executado" in captured.out
    assert "status=200" in captured.out
    assert "changed=True" in captured.out
    assert "items_found=3" in captured.out
    assert "items_ingested=2" in captured.out
    assert "items_duplicated=1" in captured.out


def test_cli_gta6_monitor_run_once_reports_no_change(
    capsys,
):
    result = {
        "url": "https://www.rockstargames.com/newswire",
        "status_code": 200,
        "change": {
            "changed": False,
        },
        "baseline": False,
        "items_found": 0,
        "items_ingested": 0,
        "items_duplicated": 0,
        "knowledge_ids": [],
    }

    with patch(
        "sys.argv",
        ["br-no-gta", "gta6-monitor", "run-once"],
    ), patch(
        "app.cli.run_gta6_monitor_once",
        return_value=result,
    ) as run_monitor:
        main()

    run_monitor.assert_called_once_with()

    captured = capsys.readouterr()

    assert "Monitor GTA6 executado" in captured.out
    assert "changed=False" in captured.out
    assert "items_found=0" in captured.out
    assert "items_ingested=0" in captured.out
    assert "items_duplicated=0" in captured.out
