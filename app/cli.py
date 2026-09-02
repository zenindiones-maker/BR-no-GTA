import argparse

from app.services.google_youtube_publication_service import (
    process_next_youtube_publication,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="br-no-gta",
        description="Operações do BR no GTA.",
    )

    subparsers = parser.add_subparsers(dest="command")

    youtube_parser = subparsers.add_parser(
        "youtube",
        help="Operações de publicação no YouTube.",
    )

    youtube_subparsers = youtube_parser.add_subparsers(
        dest="youtube_command"
    )

    youtube_subparsers.add_parser(
        "publish-next",
        help="Processa a próxima publicação YouTube pendente.",
    )

    args = parser.parse_args()

    if args.command == "youtube" and args.youtube_command == "publish-next":
        publication = process_next_youtube_publication()

        if publication is None:
            print("Nenhuma publicação YouTube pendente.")
            return

        print(
            "Publicação YouTube processada: "
            f"id={publication['id']} "
            f"status={publication['status']}"
        )
        return

    parser.print_help()


if __name__ == "__main__":
    main()
