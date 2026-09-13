import json
from unittest.mock import patch
from app.cli import main

def test_cli_gta6_monitor_routes_through_harness(capsys):
    payload=json.dumps({"operation":"br_gta6_monitor_run_once","result":{"status":"ok"}})
    with patch("sys.argv",["br-no-gta","gta6-monitor","run-once"]), patch("app.cli.br_gta6_monitor_run_once",return_value=payload) as boundary:
        main()
    boundary.assert_called_once_with(); assert "br_gta6_monitor_run_once" in capsys.readouterr().out
