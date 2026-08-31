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

    LOG_LEVEL = os.getenv("BR_LOG_LEVEL", "INFO")


settings = Settings()
