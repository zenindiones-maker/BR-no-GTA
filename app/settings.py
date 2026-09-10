from pathlib import Path
import os

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent

# Carrega a configuração local antes de qualquer os.getenv().
# Variáveis já presentes no ambiente têm prioridade.
load_dotenv(BASE_DIR / ".env", override=False)
load_dotenv(BASE_DIR / ".env.local", override=False)



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

    # GitHub Actions: executor audiovisual oficial.
    GITHUB_ACTIONS_REPOSITORY = os.getenv(
        "GITHUB_ACTIONS_REPOSITORY",
        "",
    )
    GITHUB_ACTIONS_POLL_INTERVAL = float(
        os.getenv("GITHUB_ACTIONS_POLL_INTERVAL", "5")
    )
    GITHUB_ACTIONS_RUN_TIMEOUT = float(
        os.getenv("GITHUB_ACTIONS_RUN_TIMEOUT", "3600")
    )
    GITHUB_ACTIONS_RENDER_WORKFLOW = os.getenv(
        "GITHUB_ACTIONS_RENDER_WORKFLOW",
        "render-worker.yml",
    )
    GITHUB_ACTIONS_RENDER_REF = os.getenv(
        "GITHUB_ACTIONS_RENDER_REF",
        "main",
    )
    GITHUB_ACTIONS_ARTIFACT_NAME = os.getenv(
        "GITHUB_ACTIONS_ARTIFACT_NAME",
        "render-output",
    )
    GITHUB_ACTIONS_ARTIFACT_ROOT = os.getenv(
        "GITHUB_ACTIONS_ARTIFACT_ROOT",
        "runtime/render/artifacts",
    )

settings = Settings()

# Compatibilidade de módulo para consumidores que importam `app.settings`.
GITHUB_ACTIONS_REPOSITORY = settings.GITHUB_ACTIONS_REPOSITORY
GITHUB_ACTIONS_POLL_INTERVAL = settings.GITHUB_ACTIONS_POLL_INTERVAL
GITHUB_ACTIONS_RUN_TIMEOUT = settings.GITHUB_ACTIONS_RUN_TIMEOUT
GITHUB_ACTIONS_RENDER_WORKFLOW = settings.GITHUB_ACTIONS_RENDER_WORKFLOW
GITHUB_ACTIONS_RENDER_REF = settings.GITHUB_ACTIONS_RENDER_REF
GITHUB_ACTIONS_ARTIFACT_NAME = settings.GITHUB_ACTIONS_ARTIFACT_NAME
GITHUB_ACTIONS_ARTIFACT_ROOT = settings.GITHUB_ACTIONS_ARTIFACT_ROOT
