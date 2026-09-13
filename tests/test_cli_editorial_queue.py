import json
from unittest.mock import patch
from app.cli import main

def test_cli_editorial_routes_through_harness():
    payload=json.dumps({"operation":"br_editorial_process_next","result":{"status":"ok"}})
    with patch("sys.argv",["br-no-gta","editorial","process-next"]), patch("app.cli.br_editorial_process_next",return_value=payload) as boundary:
        main()
    boundary.assert_called_once_with()
