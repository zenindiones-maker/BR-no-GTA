import argparse

from app.services.gta6_research_pipeline import (
    run_gta6_research,
)
from app.services.editorial_queue_consumer import (
    process_next_editorial_queue_item,
)
from app.services.google_youtube_publication_service import (
    process_next_youtube_publication,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="br-no-gta",
        description="Operações do BR no GTA.",
    )

    subparsers = parser.add_subparsers(dest="command")

    radar_parser = subparsers.add_parser(
        "radar",
        help="Executa o Radar de pesquisa e avaliação GTA 6.",
    )

    radar_parser.set_defaults(command_handler="radar")

    editorial_parser = subparsers.add_parser(
        "editorial",
        help="Operações da fila editorial.",
    )

    editorial_subparsers = editorial_parser.add_subparsers(
        dest="editorial_command"
    )

    editorial_subparsers.add_parser(
        "process-next",
        help="Processa o próximo item da fila editorial.",
    )

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

    if args.command == "radar":
        result = run_gta6_research()

        print(
            "Radar GTA6 executado: "
            f"total={result['total']}"
        )

        print(
            "Editorial processado: "
            f"{len(result['editorial'])}"
        )

        return

    if (
        args.command == "editorial"
        and args.editorial_command == "process-next"
    ):
        queue_result = process_next_editorial_queue_item()

        if queue_result is None:
            print("Nenhum item da fila editorial pendente.")
            return

        queue_item = queue_result["queue_item"]

        print(
            "Fila editorial processada: "
            f"id={queue_item['id']} "
            f"status={queue_result['status']}"
        )
        return

    if (
        args.command == "youtube"
        and args.youtube_command == "publish-next"
    ):
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
