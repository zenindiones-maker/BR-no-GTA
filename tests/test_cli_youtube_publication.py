from unittest.mock import patch

def test_cli_youtube_publish_next_processes_pending_publication():
    with patch(
        "app.cli.process_next_youtube_publication"
    ) as process_next:
        process_next.return_value = {
            "id": 1,
            "status": "published",
        }

        with patch("builtins.print") as mock_print:
            from app.cli import main

            with patch(
                "sys.argv",
                ["br-no-gta", "youtube", "publish-next"],
            ):
                main()

    process_next.assert_called_once_with()
    mock_print.assert_called_once_with(
        "Publicação YouTube processada: id=1 status=published"
    )
