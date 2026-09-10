import argparse

from app.services.gta6_research_pipeline import (
    run_gta6_research,
)
from app.services.editorial_queue_consumer import (
    process_next_editorial_queue_item,
)
from app.services.google_youtube_publication_service import (
    make_youtube_publication_public_with_google,
    process_next_youtube_publication,
)
from app.services.gta6_master_agent import GTA6MasterAgent
from app.services.ai_provider_factory import create_ai_provider


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

    gta6_monitor_parser = subparsers.add_parser(
        "gta6-monitor",
        help="Operações do monitor GTA 6.",
    )

    gta6_monitor_subparsers = gta6_monitor_parser.add_subparsers(
        dest="gta6_monitor_command"
    )

    gta6_monitor_subparsers.add_parser(
        "run-once",
        help="Executa uma coleta real do Rockstar Newswire.",
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

    pode_postar_parser = youtube_subparsers.add_parser(
        "pode-postar",
        help="Torna pública uma publicação YouTube pelo ID.",
    )

    pode_postar_parser.add_argument(
        "publication_id",
        type=int,
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
        ai_provider = create_ai_provider()
        queue_result = process_next_editorial_queue_item(
            ai_provider=ai_provider,
        )

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
        args.command == "gta6-monitor"
        and args.gta6_monitor_command == "run-once"
    ):
        master_result = GTA6MasterAgent().run_once()
        print(
            "GTA6 Master Agent executado: "
            f"action={master_result.action.action} "
            f"success={master_result.action.success}"
        )
        return

    if (
        args.command == "youtube"
        and args.youtube_command == "pode-postar"
    ):
        publication = make_youtube_publication_public_with_google(
            publication_id=args.publication_id,
        )

        print(
            "Publicação YouTube publicada: "
            f"id={publication['id']} "
            f"status={publication['status']}"
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
