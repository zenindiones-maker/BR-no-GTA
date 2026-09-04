from unittest.mock import patch

from app.cli import main


def test_cli_process_editorial_queue_calls_consumer(capsys):
    result = {
        "queue_item": {
            "id": 101,
            "idea_id": 202,
        },
        "status": "completed",
    }

    fake_provider = object()

    with patch(
        "sys.argv",
        ["br-no-gta", "editorial", "process-next"],
    ), patch(
        "app.cli.create_ai_provider",
        return_value=fake_provider,
    ), patch(
        "app.cli.process_next_editorial_queue_item",
        return_value=result,
    ) as process_next:
        main()

    process_next.assert_called_once_with(
        ai_provider=fake_provider,
    )

    captured = capsys.readouterr()

    assert "Fila editorial processada" in captured.out
    assert "id=101" in captured.out
    assert "status=completed" in captured.out


def test_cli_process_editorial_queue_reports_empty_queue(capsys):
    fake_provider = object()

    with patch(
        "sys.argv",
        ["br-no-gta", "editorial", "process-next"],
    ), patch(
        "app.cli.create_ai_provider",
        return_value=fake_provider,
    ), patch(
        "app.cli.process_next_editorial_queue_item",
        return_value=None,
    ) as process_next:
        main()

    process_next.assert_called_once_with(
        ai_provider=fake_provider,
    )

    captured = capsys.readouterr()

    assert "Nenhum item da fila editorial pendente" in captured.out
