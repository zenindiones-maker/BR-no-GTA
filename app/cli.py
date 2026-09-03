import argparse

from app.services.gta6_research_pipeline import (
    run_gta6_research,
)
from app.services.execution_cycle_service import (
    run_execution_cycle,
)
from app.services.editorial_queue_consumer import (
    process_next_editorial_queue_item,
)
from app.services.google_youtube_publication_service import (
    process_next_youtube_publication,
)
from app.services.gta6_monitor_run_service import (
    run_gta6_monitor_once,
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

    execution_parser = subparsers.add_parser(
        "execution",
        help="Operações do ciclo de execução.",
    )

    execution_subparsers = execution_parser.add_subparsers(
        dest="execution_command"
    )

    execution_subparsers.add_parser(
        "run-once",
        help="Executa uma unidade do ciclo operacional.",
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
        args.command == "execution"
        and args.execution_command == "run-once"
    ):
        cycle_result = run_execution_cycle()

        editorial_result = cycle_result["editorial"]
        render_result = cycle_result["render"]

        if editorial_result is None and render_result is None:
            print(
                "Nenhum trabalho pendente no ciclo de execução."
            )
            return

        editorial_status = (
            editorial_result["status"]
            if editorial_result is not None
            else "none"
        )

        render_status = (
            render_result["status"]
            if render_result is not None
            else "none"
        )

        print(
            "Ciclo de execução processado: "
            f"editorial={editorial_status} "
            f"render={render_status}"
        )
        return

    if (
        args.command == "gta6-monitor"
        and args.gta6_monitor_command == "run-once"
    ):
        monitor_result = run_gta6_monitor_once()

        print(
            "Monitor GTA6 executado: "
            f"status={monitor_result['status_code']} "
            f"changed={monitor_result['change']['changed']} "
            f"items_found={monitor_result['items_found']} "
            f"items_ingested={monitor_result['items_ingested']} "
            f"items_duplicated={monitor_result['items_duplicated']}"
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
