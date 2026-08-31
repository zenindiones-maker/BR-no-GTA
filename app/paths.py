from pathlib import Path

from app.settings import settings


PROJECT_DIRECTORIES = (
    settings.BRAIN_DIR,
    settings.CONFIG_DIR,
    settings.CONTENT_DIR,
    settings.CONTENT_RESEARCH_DIR,
    settings.CONTENT_SCRIPTS_DIR,
    settings.CONTENT_SHORTS_DIR,
    settings.CONTENT_VIDEOS_DIR,
    settings.DATA_DIR,
    settings.DATABASE_DIR,
    settings.RAW_DATA_DIR,
    settings.PROCESSED_DATA_DIR,
    settings.LOGS_DIR,
    settings.OUTPUT_DIR,
    settings.YOUTUBE_DIR,
    settings.YOUTUBE_LOGS_DIR,
    settings.YOUTUBE_SCRIPTS_DIR,
)


def ensure_project_directories() -> None:
    """Cria os diretórios estruturais que ainda não existirem."""
    for directory in PROJECT_DIRECTORIES:
        Path(directory).mkdir(parents=True, exist_ok=True)


def get_database_path() -> Path:
    """Retorna o caminho do banco SQLite do projeto."""
    return settings.DATABASE_FILE
