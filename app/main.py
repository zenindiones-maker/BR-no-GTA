from app.database.schema import initialize_schema
from app.paths import ensure_project_directories
from app.settings import settings
from app.services.gta6_monitor_scheduler_factory import (
    create_gta6_monitor_scheduler,
)
from app.services.gta6_monitor_runtime import GTA6MonitorRuntime


def initialize_application() -> None:
    """Inicializa a estrutura básica da aplicação."""
    ensure_project_directories()
    initialize_schema()


def main() -> None:
    """Ponto de entrada principal da aplicação."""
    initialize_application()

    scheduler = create_gta6_monitor_scheduler()
    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    print(f"{settings.PROJECT_NAME}: inicializado com sucesso.")
    print(f"Banco: {settings.DATABASE_FILE}")
    print("GTA6 Monitor Runtime: iniciando.")

    runtime.run_forever()


if __name__ == "__main__":
    main()
