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

CREATE TABLE IF NOT EXISTS content_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    unit_type TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    media_format TEXT NOT NULL,
    script_id INTEGER NOT NULL,
    idea_id INTEGER NOT NULL,
    objective TEXT NOT NULL,
    hook TEXT NOT NULL,
    narration TEXT NOT NULL,
    visual_requirements TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'ready',
    file_path TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (content_item_id) REFERENCES content_items(id),
    FOREIGN KEY (script_id) REFERENCES scripts(id),
    FOREIGN KEY (idea_id) REFERENCES ideas(id)
);

CREATE INDEX IF NOT EXISTS idx_content_units_content_item_id
ON content_units(content_item_id);

CREATE INDEX IF NOT EXISTS idx_content_units_status
ON content_units(status);

CREATE TABLE IF NOT EXISTS content_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_unit_id INTEGER NOT NULL,
    segment_order INTEGER NOT NULL,
    duration_seconds REAL NOT NULL,
    media_format TEXT NOT NULL,
    source_start_seconds REAL NOT NULL,
    source_end_seconds REAL NOT NULL,
    role TEXT NOT NULL DEFAULT 'content',
    status TEXT NOT NULL DEFAULT 'ready',
    file_path TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (content_unit_id)
        REFERENCES content_units(id)
        ON DELETE CASCADE,
    UNIQUE(content_unit_id, segment_order)
);

CREATE INDEX IF NOT EXISTS idx_content_segments_content_unit_id
ON content_segments(content_unit_id);

CREATE INDEX IF NOT EXISTS idx_content_segments_status
ON content_segments(status);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    file_path TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (content_item_id) REFERENCES content_items(id)
);



CREATE TABLE IF NOT EXISTS gta6_media_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    source TEXT NOT NULL,
    source_authority TEXT NOT NULL,
    channel_id TEXT,
    channel_title TEXT,
    description TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    media_type TEXT NOT NULL DEFAULT 'video',
    game TEXT NOT NULL DEFAULT 'gta6',
    relevance_score REAL NOT NULL DEFAULT 0,
    reuse_allowed INTEGER NOT NULL DEFAULT 0,
    reuse_license TEXT,
    provenance TEXT NOT NULL DEFAULT '',
    media_role TEXT NOT NULL DEFAULT 'unknown',
    status TEXT NOT NULL DEFAULT 'discovered',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_gta6_media_catalog_status
ON gta6_media_catalog(status);

CREATE INDEX IF NOT EXISTS idx_gta6_media_catalog_authority
ON gta6_media_catalog(source_authority);

CREATE INDEX IF NOT EXISTS idx_gta6_media_catalog_relevance
ON gta6_media_catalog(relevance_score);

CREATE INDEX IF NOT EXISTS idx_gta6_media_catalog_channel
ON gta6_media_catalog(channel_id);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    target_duration_seconds REAL NOT NULL,
    min_duration_seconds REAL NOT NULL,
    max_duration_seconds REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_episodes_status
ON episodes(status);

CREATE TABLE IF NOT EXISTS episode_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL,
    content_segment_id INTEGER NOT NULL,
    segment_order INTEGER NOT NULL,
    start_offset_seconds REAL NOT NULL DEFAULT 0,
    role TEXT NOT NULL DEFAULT 'content',
    status TEXT NOT NULL DEFAULT 'ready',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (episode_id)
        REFERENCES episodes(id)
        ON DELETE CASCADE,
    FOREIGN KEY (content_segment_id)
        REFERENCES content_segments(id)
        ON DELETE CASCADE,
    UNIQUE(episode_id, segment_order)
);

CREATE INDEX IF NOT EXISTS idx_episode_segments_episode_id
ON episode_segments(episode_id);

CREATE INDEX IF NOT EXISTS idx_episode_segments_content_segment_id
ON episode_segments(content_segment_id);

CREATE INDEX IF NOT EXISTS idx_episode_segments_status
ON episode_segments(status);

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



def _migrate_memory_record_claims(connection) -> None:
    """Cria a linhagem persistente entre memória semântica e Claims."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_record_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_record_id INTEGER NOT NULL,
            claim_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (memory_record_id)
                REFERENCES memory_records(id)
                ON DELETE RESTRICT,
            FOREIGN KEY (claim_id)
                REFERENCES memory_claims(id)
                ON DELETE RESTRICT,
            UNIQUE(memory_record_id, claim_id)
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_record_claims_record
        ON memory_record_claims(memory_record_id)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_record_claims_claim
        ON memory_record_claims(claim_id)
        """
    )


def _migrate_memory_claims(connection) -> None:
    """Cria a persistência das afirmações derivadas do Brain."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim TEXT NOT NULL,
            claim_type TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 5.0,
            status TEXT NOT NULL DEFAULT 'active',
            scope TEXT NOT NULL DEFAULT 'gta6',
            valid_at TEXT,
            invalid_at TEXT,
            extraction_method TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(memory_claims)"
        ).fetchall()
    }

    if "canonical_key" not in columns:
        connection.execute(
            "ALTER TABLE memory_claims "
            "ADD COLUMN canonical_key TEXT NOT NULL DEFAULT ''"
        )

    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
        idx_memory_claims_canonical_key
        ON memory_claims(canonical_key)
        WHERE canonical_key != ''
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_claims_type
        ON memory_claims(claim_type)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_claims_status
        ON memory_claims(status)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_claims_scope
        ON memory_claims(scope)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_claims_confidence
        ON memory_claims(confidence)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_claims_validity
        ON memory_claims(valid_at, invalid_at)
        """
    )


def _migrate_memory_claim_evidence(connection) -> None:
    """Cria a ligação persistente entre claims e evidências."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_claim_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id INTEGER NOT NULL,
            event_id INTEGER NOT NULL,
            evidence_role TEXT NOT NULL DEFAULT 'supporting',
            weight REAL NOT NULL DEFAULT 1.0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (claim_id)
                REFERENCES memory_claims(id)
                ON DELETE RESTRICT,
            FOREIGN KEY (event_id)
                REFERENCES memory_events(id)
                ON DELETE RESTRICT,
            UNIQUE(claim_id, event_id)
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_claim_evidence_claim
        ON memory_claim_evidence(claim_id)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_claim_evidence_event
        ON memory_claim_evidence(event_id)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_claim_evidence_role
        ON memory_claim_evidence(evidence_role)
        """
    )


def _migrate_memory_events(connection) -> None:
    """Cria o log append-only de evidências do Brain."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT,
            content TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'gta6',
            occurred_at TEXT,
            observed_at TEXT,
            provenance TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_events_type
        ON memory_events(event_type)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_events_source
        ON memory_events(source_type, source_id)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_events_scope
        ON memory_events(scope)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_events_observed
        ON memory_events(observed_at)
        """
    )


def _migrate_memory_records(connection) -> None:
    """Cria a persistência base das memórias do Brain."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_type TEXT NOT NULL,
            content TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT,
            confidence REAL NOT NULL DEFAULT 5.0,
            importance REAL NOT NULL DEFAULT 5.0,
            scope TEXT NOT NULL DEFAULT 'gta6',
            valid_at TEXT,
            invalid_at TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            access_count INTEGER NOT NULL DEFAULT 0,
            last_accessed_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_records_type
        ON memory_records(memory_type)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_records_scope
        ON memory_records(scope)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_records_status
        ON memory_records(status)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_memory_records_source
        ON memory_records(source_type, source_id)
        """
    )


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


def _migrate_media_knowledge(connection) -> None:
    """Cria a persistência dos resultados de análise multimídia."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS media_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL,
            analysis_version TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_media_knowledge_source_path
        ON media_knowledge(source_path)
        """
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



def _migrate_speech_analysis(connection) -> None:
    """Cria a persistência das análises especializadas de fala."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS speech_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_knowledge_id INTEGER NOT NULL,
            source_path TEXT NOT NULL,
            source_language TEXT NOT NULL,
            language_probability REAL NOT NULL,
            analysis_version TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            model_version TEXT,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (media_knowledge_id)
                REFERENCES media_knowledge(id)
                ON DELETE CASCADE
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_speech_analysis_media_knowledge
        ON speech_analysis(media_knowledge_id)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_speech_analysis_source_language
        ON speech_analysis(source_language)
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


def _migrate_gta6_monitor_runs(connection) -> None:
    """Cria a persistência das execuções do monitor GTA 6."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gta6_monitor_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            url TEXT NOT NULL,
            status_code INTEGER,
            baseline INTEGER NOT NULL DEFAULT 0,
            items_found INTEGER NOT NULL DEFAULT 0,
            items_ingested INTEGER NOT NULL DEFAULT 0,
            items_duplicated INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

def _migrate_gta6_master_agent_runs(connection) -> None:
    """Cria a persistência dos ciclos operacionais do GTA6 Master Agent."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gta6_master_agent_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id TEXT NOT NULL,
            cycle_number INTEGER NOT NULL,
            status TEXT NOT NULL,
            action TEXT NOT NULL,
            reason TEXT NOT NULL,
            priority TEXT NOT NULL,
            confidence REAL NOT NULL,
            tool TEXT,
            success INTEGER NOT NULL,
            result_json TEXT NOT NULL,
            error_type TEXT,
            error TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_gta6_master_agent_runs_execution_id
        ON gta6_master_agent_runs(execution_id)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_gta6_master_agent_runs_status
        ON gta6_master_agent_runs(status)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_gta6_master_agent_runs_action
        ON gta6_master_agent_runs(action)
        """
    )


def _migrate_gta6_scheduler_events(connection) -> None:
    """Cria a persistência dos eventos operacionais do scheduler GTA 6."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gta6_scheduler_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            scheduled_run_time TEXT,
            scheduled_run_times TEXT,
            observed_at TEXT NOT NULL,
            exception TEXT,
            traceback_text TEXT,
            run_id INTEGER,
            execution_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _migrate_gta6_media_intelligence(connection) -> None:
    """Persiste os sinais calculados pelo GTA6 Media Intelligence no catálogo."""

    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(gta6_media_catalog)"
        ).fetchall()
    }

    additions = {
        "topic_relevance": "REAL NOT NULL DEFAULT 0",
        "trend_relevance": "REAL NOT NULL DEFAULT 0",
        "opportunity_score": "REAL NOT NULL DEFAULT 0",
        "evidence_score": "REAL NOT NULL DEFAULT 0",
        "authority_score": "REAL NOT NULL DEFAULT 0",
        "freshness_score": "REAL NOT NULL DEFAULT 0",
        "visual_value": "REAL NOT NULL DEFAULT 0",
        "information_value": "REAL NOT NULL DEFAULT 0",
        "editorial_relevance": "REAL NOT NULL DEFAULT 0",
        "intelligence_score": "REAL NOT NULL DEFAULT 0",
        "editorial_role": "TEXT NOT NULL DEFAULT 'unknown'",
        "intelligence_reasons": "TEXT NOT NULL DEFAULT '[]'",
    }

    for column_name, definition in additions.items():
        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE gta6_media_catalog "
                f"ADD COLUMN {column_name} {definition}"
            )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_gta6_media_catalog_intelligence_score
        ON gta6_media_catalog(intelligence_score)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_gta6_media_catalog_opportunity_score
        ON gta6_media_catalog(opportunity_score)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_gta6_media_catalog_evidence_score
        ON gta6_media_catalog(evidence_score)
        """
    )


def _migrate_gta6_goals(connection) -> None:
    """Cria a persistência do Goal Engine do GTA6."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gta6_goals (
            goal_id TEXT PRIMARY KEY,
            goal_type TEXT NOT NULL,
            topic TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'DISCOVERED',
            priority TEXT NOT NULL DEFAULT 'MEDIUM',
            opportunity_score REAL NOT NULL DEFAULT 0,
            target_duration TEXT,
            current_stage TEXT NOT NULL DEFAULT 'DISCOVERY',
            last_published_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_gta6_goals_status
        ON gta6_goals(status)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_gta6_goals_type
        ON gta6_goals(goal_type)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_gta6_goals_topic
        ON gta6_goals(topic)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_gta6_goals_priority
        ON gta6_goals(priority)
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gta6_goal_claims (
            goal_id TEXT NOT NULL,
            claim_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (goal_id, claim_id),
            FOREIGN KEY (goal_id)
                REFERENCES gta6_goals(goal_id)
                ON DELETE CASCADE,
            FOREIGN KEY (claim_id)
                REFERENCES memory_claims(id)
                ON DELETE RESTRICT
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_gta6_goal_claims_claim
        ON gta6_goal_claims(claim_id)
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gta6_goal_artifacts (
            goal_id TEXT PRIMARY KEY,
            idea_id INTEGER,
            script_id INTEGER,
            content_item_id INTEGER,
            video_id INTEGER,
            render_job_id INTEGER,
            youtube_publication_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (goal_id)
                REFERENCES gta6_goals(goal_id)
                ON DELETE CASCADE,
            FOREIGN KEY (idea_id)
                REFERENCES ideas(id)
                ON DELETE SET NULL,
            FOREIGN KEY (script_id)
                REFERENCES scripts(id)
                ON DELETE SET NULL,
            FOREIGN KEY (content_item_id)
                REFERENCES content_items(id)
                ON DELETE SET NULL,
            FOREIGN KEY (video_id)
                REFERENCES videos(id)
                ON DELETE SET NULL,
            FOREIGN KEY (render_job_id)
                REFERENCES render_jobs(id)
                ON DELETE SET NULL,
            FOREIGN KEY (youtube_publication_id)
                REFERENCES youtube_publications(id)
                ON DELETE SET NULL
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_gta6_goal_artifacts_idea
        ON gta6_goal_artifacts(idea_id)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_gta6_goal_artifacts_script
        ON gta6_goal_artifacts(script_id)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_gta6_goal_artifacts_content
        ON gta6_goal_artifacts(content_item_id)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_gta6_goal_artifacts_video
        ON gta6_goal_artifacts(video_id)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_gta6_goal_artifacts_render
        ON gta6_goal_artifacts(render_job_id)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_gta6_goal_artifacts_youtube
        ON gta6_goal_artifacts(youtube_publication_id)
        """
    )

def initialize_schema() -> None:
    """Cria as tabelas estruturais e aplica migrações necessárias."""

    connection = get_connection()

    try:
        connection.executescript(SCHEMA_SQL)
        _migrate_ideas_research_item_id(connection)
        _migrate_memory_records(connection)
        _migrate_memory_claims(connection)
        _migrate_memory_record_claims(connection)
        _migrate_memory_claim_evidence(connection)
        _migrate_memory_events(connection)
        _migrate_youtube_publication_file_path(connection)
        _migrate_gta6_knowledge(connection)
        _migrate_media_knowledge(connection)
        _migrate_speech_analysis(connection)
        _migrate_gta6_knowledge_source_name(connection)
        _migrate_gta6_monitor_state(connection)
        _migrate_gta6_monitor_events(connection)
        _migrate_gta6_monitor_runs(connection)
        _migrate_gta6_master_agent_runs(connection)
        _migrate_gta6_scheduler_events(connection)
        _migrate_gta6_goals(connection)
        _migrate_gta6_media_intelligence(connection)
        connection.commit()
    finally:
        connection.close()
