import os
from pathlib import Path

from app.settings import settings


def get_database_file() -> Path:
    """Retorna o banco ativo do projeto."""

    test_database = os.getenv("BR_TEST_DATABASE")

    if test_database:
        return Path(test_database)

    return settings.DATABASE_FILE
