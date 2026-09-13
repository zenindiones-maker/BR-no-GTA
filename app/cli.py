import argparse
import json

def br_research_run():
    from app.integrations.deepseek_harness.server import br_research_run as operation
    return operation()

def br_editorial_process_next():
    from app.integrations.deepseek_harness.server import br_editorial_process_next as operation
    return operation()

def br_gta6_monitor_run_once():
    from app.integrations.deepseek_harness.server import br_gta6_monitor_run_once as operation
    return operation()

def br_youtube_pode_postar(publication_id: int):
    from app.integrations.deepseek_harness.server import br_youtube_pode_postar as operation
    return operation(publication_id=publication_id)

def br_youtube_publish_next():
    from app.integrations.deepseek_harness.server import br_youtube_publish_next as operation
    return operation()



def _print_harness_result(raw: str) -> None:
    print(json.dumps(json.loads(raw), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="br-no-gta", description="Operações do BR no GTA via DeepSeek Harness.")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("radar")
    editorial = subparsers.add_parser("editorial")
    editorial.add_subparsers(dest="editorial_command").add_parser("process-next")
    monitor = subparsers.add_parser("gta6-monitor")
    monitor.add_subparsers(dest="gta6_monitor_command").add_parser("run-once")
    youtube = subparsers.add_parser("youtube")
    youtube_sub = youtube.add_subparsers(dest="youtube_command")
    youtube_sub.add_parser("publish-next")
    pode = youtube_sub.add_parser("pode-postar")
    pode.add_argument("publication_id", type=int)
    args = parser.parse_args()

    if args.command == "radar":
        _print_harness_result(br_research_run()); return
    if args.command == "editorial" and args.editorial_command == "process-next":
        _print_harness_result(br_editorial_process_next()); return
    if args.command == "gta6-monitor" and args.gta6_monitor_command == "run-once":
        _print_harness_result(br_gta6_monitor_run_once()); return
    if args.command == "youtube" and args.youtube_command == "pode-postar":
        _print_harness_result(br_youtube_pode_postar(args.publication_id)); return
    if args.command == "youtube" and args.youtube_command == "publish-next":
        _print_harness_result(br_youtube_publish_next()); return
    parser.print_help()


if __name__ == "__main__":
    main()
