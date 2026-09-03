from unittest.mock import patch

from app.cli import main


def test_cli_execution_run_once_calls_execution_cycle(capsys):
    result = {
        "editorial": {
            "queue_item": {
                "id": 101,
                "idea_id": 202,
            },
            "status": "completed",
        },
        "render": {
            "id": 303,
            "status": "completed",
        },
    }

    with patch(
        "sys.argv",
        ["br-no-gta", "execution", "run-once"],
    ), patch(
        "app.cli.run_execution_cycle",
        return_value=result,
    ) as run_cycle:
        main()

    run_cycle.assert_called_once_with()

    captured = capsys.readouterr()

    assert "Ciclo de execução processado" in captured.out
    assert "editorial=completed" in captured.out
    assert "render=completed" in captured.out


def test_cli_execution_run_once_reports_empty_cycle(capsys):
    with patch(
        "sys.argv",
        ["br-no-gta", "execution", "run-once"],
    ), patch(
        "app.cli.run_execution_cycle",
        return_value={
            "editorial": None,
            "render": None,
        },
    ) as run_cycle:
        main()

    run_cycle.assert_called_once_with()

    captured = capsys.readouterr()

    assert "Nenhum trabalho pendente no ciclo de execução" in captured.out
