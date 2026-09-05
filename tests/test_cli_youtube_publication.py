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

def test_cli_youtube_pode_postar_publishes_publication():
    with patch(
        "app.cli.make_youtube_publication_public_with_google"
    ) as make_public:
        make_public.return_value = {
            "id": 42,
            "status": "published",
        }

        with patch("builtins.print") as mock_print:
            from app.cli import main

            with patch(
                "sys.argv",
                [
                    "br-no-gta",
                    "youtube",
                    "pode-postar",
                    "42",
                ],
            ):
                main()

    make_public.assert_called_once_with(
        publication_id=42,
    )

    mock_print.assert_called_once_with(
        "Publicação YouTube publicada: id=42 status=published"
    )

def test_cli_youtube_pode_postar_does_not_process_next():
    with patch(
        "app.cli.make_youtube_publication_public_with_google"
    ) as make_public, patch(
        "app.cli.process_next_youtube_publication"
    ) as process_next:
        make_public.return_value = {
            "id": 42,
            "status": "published",
        }

        with patch(
            "sys.argv",
            [
                "br-no-gta",
                "youtube",
                "pode-postar",
                "42",
            ],
        ):
            from app.cli import main

            main()

    make_public.assert_called_once_with(
        publication_id=42,
    )
    process_next.assert_not_called()
