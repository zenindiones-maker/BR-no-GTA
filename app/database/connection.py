import sqlite3
from pathlib import Path

from app.database.config import get_database_file
from app.paths import ensure_project_directories


def get_connection() -> sqlite3.Connection:
    """Abre uma conexão com o banco SQLite ativo."""

    database_path = Path(get_database_file())
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection
