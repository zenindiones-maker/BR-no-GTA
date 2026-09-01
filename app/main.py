from app.database.schema import initialize_schema
from app.paths import ensure_project_directories
from app.settings import settings


def initialize_application() -> None:
    """Inicializa a estrutura básica da aplicação."""
    ensure_project_directories()
    initialize_schema()


def main() -> None:
    """Ponto de entrada principal da aplicação."""
    initialize_application()

    print(f"{settings.PROJECT_NAME}: inicializado com sucesso.")
    print(f"Banco: {settings.DATABASE_FILE}")


if __name__ == "__main__":
    main()
