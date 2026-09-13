import json
from unittest.mock import patch
from app.cli import main

def test_cli_radar_routes_through_harness():
    payload=json.dumps({"operation":"br_research_run","result":{"total":1}})
    with patch("sys.argv",["br-no-gta","radar"]), patch("app.cli.br_research_run",return_value=payload) as boundary:
        main()
    boundary.assert_called_once_with()
