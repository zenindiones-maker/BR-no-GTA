from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings:
    PROJECT_NAME = "BR no GTA"

    BASE_DIR = BASE_DIR
    BRAIN_DIR = BASE_DIR / "brain"
    CONFIG_DIR = BASE_DIR / "config"
    CONTENT_DIR = BASE_DIR / "content"
    DATA_DIR = BASE_DIR / "data"
    LOGS_DIR = BASE_DIR / "logs"
    OUTPUT_DIR = BASE_DIR / "output"
    YOUTUBE_DIR = BASE_DIR / "YouTube"

    DATABASE_DIR = DATA_DIR / "database"
    RAW_DATA_DIR = DATA_DIR / "raw"
    PROCESSED_DATA_DIR = DATA_DIR / "processed"

    CONTENT_RESEARCH_DIR = CONTENT_DIR / "research"
    CONTENT_SCRIPTS_DIR = CONTENT_DIR / "scripts"
    CONTENT_SHORTS_DIR = CONTENT_DIR / "shorts"
    CONTENT_VIDEOS_DIR = CONTENT_DIR / "videos"

    YOUTUBE_CREDENTIALS_DIR = YOUTUBE_DIR / "credentials"
    YOUTUBE_TOKENS_DIR = YOUTUBE_DIR / "tokens"
    YOUTUBE_LOGS_DIR = YOUTUBE_DIR / "logs"
    YOUTUBE_SCRIPTS_DIR = YOUTUBE_DIR / "scripts"

    DATABASE_FILE = DATABASE_DIR / "br_no_gta.db"

    LOG_LEVEL = os.getenv(
        "BR_LOG_LEVEL",
        "INFO",
    )

    ROCKSTAR_QUERY_HASH = os.getenv(
        "BR_ROCKSTAR_QUERY_HASH",
    )

    # Fontes oficiais de mídia GTA6.
    # O Brain usa essas fontes como prioridade para descoberta
    # audiovisual antes de ampliar a pesquisa para terceiros.
    GTA6_OFFICIAL_YOUTUBE_CHANNEL_IDS = (
        "UC6VcWc1rAoWdBCM0JxrRQ3A",
    )

    GTA6_OFFICIAL_MEDIA_URL = (
        "https://www.rockstargames.com/VI/media/videos"
    )

    # MoneyPrinterTurbo

# MoneyPrinterTurbo SSH / rsync
#
# O MPT roda exclusivamente na máquina de produção.
# O BR apenas controla a execução através de SSH/rsync.
#
# Não inicia API HTTP do MoneyPrinterTurbo.

MPT_SSH_HOST = os.getenv(
    "BR_MPT_SSH_HOST",
    "",
)

MPT_SSH_USER = os.getenv(
    "BR_MPT_SSH_USER",
    "",
)

MPT_SSH_PORT = int(
    os.getenv(
        "BR_MPT_SSH_PORT",
        "22",
    )
)

MPT_SSH_KEY = os.getenv(
    "BR_MPT_SSH_KEY",
    "",
)

MPT_REMOTE_ROOT = os.getenv(
    "BR_MPT_REMOTE_ROOT",
    "/opt/money-printer-turbo",
)

MPT_REMOTE_RUNNER = os.getenv(
    "BR_MPT_REMOTE_RUNNER",
    "/opt/money-printer-turbo/"
    "money_printer_turbo_remote_runner.py",
)

MPT_SSH_CONNECT_TIMEOUT = float(
    os.getenv(
        "BR_MPT_SSH_CONNECT_TIMEOUT",
        "30",
    )
)

MPT_SSH_COMMAND_TIMEOUT = float(
    os.getenv(
        "BR_MPT_SSH_COMMAND_TIMEOUT",
        "3600",
    )
)

MPT_LOCAL_INPUT_ROOT = os.getenv(
    "BR_MPT_LOCAL_INPUT_ROOT",
    "storage/money_printer_turbo",
)

#
# O MPT é opcional no ambiente do BR.
# Quando essas variáveis não existem, o sistema
# continua funcionando normalmente sem MPT.

MPT_BASE_URL = os.getenv(
    "BR_MPT_BASE_URL",
    "",
)

MPT_API_KEY = os.getenv(
    "BR_MPT_API_KEY",
    "",
)

MPT_TIMEOUT = float(
    os.getenv(
        "BR_MPT_TIMEOUT",
        "30",
    )
)

MPT_POLL_INTERVAL = float(
    os.getenv(
        "BR_MPT_POLL_INTERVAL",
        "5",
    )
)

MPT_MAX_POLLS = int(
    os.getenv(
        "BR_MPT_MAX_POLLS",
        "120",
    )
)


settings = Settings()
