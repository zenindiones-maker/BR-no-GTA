from app.database.connection import get_connection


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT,
    source_type TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS research_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    title TEXT NOT NULL,
    content TEXT,
    url TEXT,
    published_at TEXT,
    collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    score REAL,
    research_item_id INTEGER UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (research_item_id) REFERENCES research_items(id)
);

CREATE TABLE IF NOT EXISTS editorial_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id INTEGER NOT NULL,
    priority_score REAL NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    queued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    FOREIGN KEY (idea_id) REFERENCES ideas(id)
);

CREATE TABLE IF NOT EXISTS content_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    file_path TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    file_path TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (content_item_id) REFERENCES content_items(id)
);


CREATE TABLE IF NOT EXISTS youtube_publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL UNIQUE,
    content_item_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    category_id TEXT NOT NULL,
    file_path TEXT,
    privacy_status TEXT NOT NULL DEFAULT 'private',
    publish_at TEXT,
    youtube_video_id TEXT,
    youtube_url TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at TEXT,
    FOREIGN KEY (video_id) REFERENCES videos(id),
    FOREIGN KEY (content_item_id) REFERENCES content_items(id)
);

CREATE TABLE IF NOT EXISTS scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(idea_id, version),
    FOREIGN KEY (idea_id) REFERENCES ideas(id)
);

CREATE TABLE IF NOT EXISTS render_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER NOT NULL,
    script_id INTEGER NOT NULL,
    idea_id INTEGER NOT NULL,
    objective TEXT NOT NULL,
    format TEXT NOT NULL,
    estimated_duration_seconds REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    payload TEXT NOT NULL,
    job_type TEXT NOT NULL,
    queue TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS editorial_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    research_item_id INTEGER NOT NULL,
    idea_id INTEGER NOT NULL,
    score REAL NOT NULL,
    decision TEXT NOT NULL,
    relevance REAL NOT NULL,
    novelty REAL NOT NULL,
    interest REAL NOT NULL,
    click_potential REAL NOT NULL,
    timeliness REAL NOT NULL,
    source_reliability REAL NOT NULL,
    video_potential REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (research_item_id) REFERENCES research_items(id),
    FOREIGN KEY (idea_id) REFERENCES ideas(id)
);
"""


def _migrate_ideas_research_item_id(connection) -> None:
    """Adiciona a relação pesquisa -> ideia em bancos existentes."""

    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(ideas)"
        ).fetchall()
    }

    if "research_item_id" not in columns:
        connection.execute(
            "ALTER TABLE ideas ADD COLUMN research_item_id INTEGER"
        )

    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
        idx_ideas_research_item_id
        ON ideas(research_item_id)
        WHERE research_item_id IS NOT NULL
        """
    )



def _migrate_youtube_publication_file_path(connection) -> None:
    """Adiciona o caminho do arquivo à intenção de publicação no YouTube."""

    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(youtube_publications)"
        ).fetchall()
    }

    if "file_path" not in columns:
        connection.execute(
            "ALTER TABLE youtube_publications ADD COLUMN file_path TEXT"
        )


def _migrate_gta6_knowledge(connection) -> None:
    """Cria a camada de conhecimento especializada em GTA 6."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gta6_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            research_item_id INTEGER NOT NULL UNIQUE,
            source_name TEXT NOT NULL DEFAULT '',
            fact_type TEXT NOT NULL,
            confidence TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (research_item_id)
                REFERENCES research_items(id)
        )
        """
    )


def _migrate_gta6_monitor_events(connection) -> None:
    """Cria a persistência dos eventos de mudança dos monitores GTA 6."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gta6_monitor_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            previous_hash TEXT,
            current_hash TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _migrate_gta6_monitor_state(connection) -> None:
    """Cria a persistência mínima do estado dos monitores GTA 6."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gta6_monitor_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            content_hash TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )



def _migrate_gta6_knowledge_source_name(connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(gta6_knowledge)"
        ).fetchall()
    }

    if "source_name" not in columns:
        connection.execute(
            "ALTER TABLE gta6_knowledge "
            "ADD COLUMN source_name TEXT NOT NULL DEFAULT ''"
        )

def initialize_schema() -> None:
    """Cria as tabelas estruturais e aplica migrações necessárias."""

    connection = get_connection()

    try:
        connection.executescript(SCHEMA_SQL)
        _migrate_ideas_research_item_id(connection)
        _migrate_youtube_publication_file_path(connection)
        _migrate_gta6_knowledge(connection)
        _migrate_gta6_knowledge_source_name(connection)
        _migrate_gta6_monitor_state(connection)
        _migrate_gta6_monitor_events(connection)
        connection.commit()
    finally:
        connection.close()
