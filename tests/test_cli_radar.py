from unittest.mock import patch


def test_cli_radar_runs_gta6_research():
    radar_result = {
        "rockstar_monitor": {"changed": True},
        "rockstar_newswire": [
            {"research_item_id": 1},
        ],
        "news_feeds": [
            {"research_item_id": 2},
        ],
        "total": 2,
        "editorial": [
            {"idea_id": 1, "decision": "approve"},
        ],
    }

    with patch(
        "app.cli.run_gta6_research"
    ) as run_research:
        run_research.return_value = radar_result

        with patch("builtins.print") as mock_print:
            from app.cli import main

            with patch(
                "sys.argv",
                ["br-no-gta", "radar"],
            ):
                main()

    run_research.assert_called_once_with()

    mock_print.assert_any_call(
        "Radar GTA6 executado: total=2"
    )

    mock_print.assert_any_call(
        "Editorial processado: 1"
    )
