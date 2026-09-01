import sqlite3
from pathlib import Path

from app.paths import ensure_project_directories, get_database_path


def get_connection() -> sqlite3.Connection:
    """Abre uma conexão com o banco SQLite do projeto."""
    ensure_project_directories()

    database_path = Path(get_database_path())

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row

    return connection
