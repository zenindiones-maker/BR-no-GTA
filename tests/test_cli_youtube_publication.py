import json
from unittest.mock import patch
from app.cli import main

def test_cli_youtube_publish_next_routes_through_harness():
    payload=json.dumps({"operation":"br_youtube_publish_next","result":None})
    with patch("sys.argv",["br-no-gta","youtube","publish-next"]), patch("app.cli.br_youtube_publish_next",return_value=payload) as boundary:
        main()
    boundary.assert_called_once_with()

def test_cli_youtube_pode_postar_routes_through_harness():
    payload=json.dumps({"operation":"br_youtube_pode_postar","result":{"id":42}})
    with patch("sys.argv",["br-no-gta","youtube","pode-postar","42"]), patch("app.cli.br_youtube_pode_postar",return_value=payload) as boundary:
        main()
    boundary.assert_called_once_with(42)
