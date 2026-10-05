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
    asset_ref TEXT,
    source_url TEXT,
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

CREATE TABLE IF NOT EXISTS youtube_content_packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id TEXT NOT NULL UNIQUE,
    content_item_id INTEGER NOT NULL UNIQUE,
    script_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    search_intent TEXT NOT NULL,
    thumbnail_concept TEXT NOT NULL,
    thumbnail_copy TEXT,
    strategy_analysis TEXT NOT NULL DEFAULT '',
    script_review TEXT NOT NULL DEFAULT '',
    seo_analysis TEXT NOT NULL DEFAULT '',
    production_analysis TEXT NOT NULL DEFAULT '',
    evidence_refs TEXT NOT NULL DEFAULT '[]',
    provenance TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (content_item_id) REFERENCES content_items(id),
    FOREIGN KEY (script_id) REFERENCES scripts(id)
);

CREATE INDEX IF NOT EXISTS idx_youtube_content_packages_status
ON youtube_content_packages(status, updated_at);

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



def _migrate_content_segment_asset_identity(connection) -> None:
    """Adiciona identidade estável de asset aos segmentos existentes."""

    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(content_segments)"
        ).fetchall()
    }

    if "asset_ref" not in columns:
        connection.execute(
            "ALTER TABLE content_segments ADD COLUMN asset_ref TEXT"
        )

    if "source_url" not in columns:
        connection.execute(
            "ALTER TABLE content_segments ADD COLUMN source_url TEXT"
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


def _migrate_youtube_publication_cloud_execution(connection) -> None:
    """Persist GitHub Actions upload execution metadata on the canonical Publication."""
    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(youtube_publications)"
        ).fetchall()
    }
    if "cloud_execution" not in columns:
        connection.execute(
            "ALTER TABLE youtube_publications ADD COLUMN cloud_execution TEXT"
        )



def _migrate_youtube_content_packages(connection) -> None:
    """Create the canonical pre-publication YouTube package table."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS youtube_content_packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id TEXT NOT NULL UNIQUE,
            content_item_id INTEGER NOT NULL UNIQUE,
            script_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]',
            search_intent TEXT NOT NULL,
            thumbnail_concept TEXT NOT NULL,
            thumbnail_copy TEXT,
            strategy_analysis TEXT NOT NULL DEFAULT '',
            script_review TEXT NOT NULL DEFAULT '',
            seo_analysis TEXT NOT NULL DEFAULT '',
            production_analysis TEXT NOT NULL DEFAULT '',
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            provenance TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'planned',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(content_item_id) REFERENCES content_items(id),
            FOREIGN KEY(script_id) REFERENCES scripts(id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_youtube_content_packages_status "
        "ON youtube_content_packages(status, updated_at)"
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

def _migrate_production_plans(connection) -> None:
    """Cria a persistência do Production Plan por Content Item."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS production_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_item_id INTEGER NOT NULL UNIQUE,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ready',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (content_item_id)
                REFERENCES content_items(id)
                ON DELETE CASCADE
        )
        """
    )


def _migrate_harness_authorizations(connection) -> None:
    """Persist Harness-issued authorization provenance in the central SQLite DB."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS harness_authorizations (
            authorization_id TEXT PRIMARY KEY,
            harness_decision_id TEXT NOT NULL,
            execution_id TEXT NOT NULL,
            authorized_action TEXT NOT NULL,
            subject TEXT NOT NULL,
            issued_by TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            status TEXT NOT NULL,
            lineage TEXT NOT NULL DEFAULT '{}',
            consumed_at TEXT,
            revoked_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_harness_authorizations_execution ON harness_authorizations(execution_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_harness_authorizations_decision ON harness_authorizations(harness_decision_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_harness_authorizations_subject_status ON harness_authorizations(subject, status)"
    )


def _migrate_trusted_security_review_receipts(connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS trusted_security_review_receipts (
            receipt_ref TEXT PRIMARY KEY,
            receipt_sha256 TEXT NOT NULL UNIQUE,
            candidate_sha TEXT NOT NULL,
            candidate_tree_sha TEXT NOT NULL,
            reviewed_diff_sha256 TEXT NOT NULL,
            reviewer_authorization_id TEXT NOT NULL,
            reviewer_authorization_status TEXT NOT NULL,
            reviewer_execution_principal_ref TEXT NOT NULL,
            reviewer_execution_principal_sha256 TEXT NOT NULL,
            review_independence_ref TEXT NOT NULL,
            review_independence_sha256 TEXT NOT NULL,
            review_independence_decision TEXT NOT NULL,
            reviewed_task_result_ref TEXT NOT NULL,
            reviewed_task_result_sha256 TEXT NOT NULL,
            reviewer_session_ref TEXT NOT NULL,
            final_disposition TEXT NOT NULL,
            issued_by TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_trusted_security_review_candidate
        ON trusted_security_review_receipts(candidate_sha, candidate_tree_sha, reviewed_diff_sha256);
        CREATE INDEX IF NOT EXISTS idx_trusted_security_review_authorization
        ON trusted_security_review_receipts(reviewer_authorization_id);
        """
    )


def _migrate_harness_learning_plane(connection) -> None:
    """Persist Harness-governed operational learning without creating a second Brain."""

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS harness_episodes (
            episode_id TEXT PRIMARY KEY,
            goal_id TEXT NOT NULL,
            decision_id TEXT NOT NULL,
            execution_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            parent_task_id TEXT,
            agent_id TEXT NOT NULL,
            capability_id TEXT NOT NULL,
            skill_id TEXT,
            skill_version TEXT,
            provider TEXT,
            domain TEXT NOT NULL,
            task_class TEXT NOT NULL,
            input_refs TEXT NOT NULL DEFAULT '[]',
            output_refs TEXT NOT NULL DEFAULT '[]',
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            tool_calls TEXT NOT NULL DEFAULT '[]',
            routing_decision TEXT NOT NULL DEFAULT '{}',
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            duration_seconds REAL NOT NULL,
            status TEXT NOT NULL,
            actual_outcome TEXT NOT NULL DEFAULT '{}',
            outcome_evidence TEXT NOT NULL DEFAULT '[]',
            error TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            human_intervention INTEGER NOT NULL DEFAULT 0,
            qa_results TEXT NOT NULL DEFAULT '{}',
            cost REAL,
            latency_seconds REAL,
            commit_ref TEXT,
            run_ref TEXT,
            artifact_refs TEXT NOT NULL DEFAULT '[]',
            source_versions TEXT NOT NULL DEFAULT '{}',
            lineage TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(execution_id, task_id, capability_id, agent_id)
        );

        CREATE INDEX IF NOT EXISTS idx_harness_episodes_goal
        ON harness_episodes(goal_id);

        CREATE INDEX IF NOT EXISTS idx_harness_episodes_capability
        ON harness_episodes(capability_id, task_class, domain);

        CREATE INDEX IF NOT EXISTS idx_harness_episodes_status
        ON harness_episodes(status);

        CREATE TABLE IF NOT EXISTS harness_memories (
            memory_id TEXT PRIMARY KEY,
            memory_type TEXT NOT NULL,
            claim TEXT NOT NULL,
            domain TEXT NOT NULL,
            task_class TEXT,
            failure_pattern TEXT,
            source_episode_ids TEXT NOT NULL DEFAULT '[]',
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            agent_id TEXT,
            capability_id TEXT,
            skill_id TEXT,
            skill_version TEXT,
            source_versions TEXT NOT NULL DEFAULT '{}',
            metadata TEXT NOT NULL DEFAULT '{}',
            support_count INTEGER NOT NULL DEFAULT 0,
            contradiction_count INTEGER NOT NULL DEFAULT 0,
            confidence REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'CANDIDATE',
            fingerprint TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            last_verified_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_harness_memories_retrieval
        ON harness_memories(status, domain, task_class, capability_id);

        CREATE INDEX IF NOT EXISTS idx_harness_memories_type
        ON harness_memories(memory_type, status);

        CREATE TABLE IF NOT EXISTS harness_competence (
            competence_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            skill_id TEXT,
            capability_id TEXT NOT NULL,
            domain TEXT NOT NULL,
            task_class TEXT NOT NULL,
            version TEXT NOT NULL,
            tested_cases INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            failure_count INTEGER NOT NULL DEFAULT 0,
            human_correction_count INTEGER NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0,
            total_latency_seconds REAL NOT NULL DEFAULT 0,
            total_cost REAL NOT NULL DEFAULT 0,
            known_failure_modes TEXT NOT NULL DEFAULT '[]',
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            last_verified_at TEXT,
            confidence REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'UNVERIFIED',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(agent_id, capability_id, task_class, version)
        );

        CREATE INDEX IF NOT EXISTS idx_harness_competence_route
        ON harness_competence(status, domain, task_class, capability_id);

        CREATE TABLE IF NOT EXISTS harness_learning_candidates (
            candidate_id TEXT PRIMARY KEY,
            candidate_type TEXT NOT NULL,
            hypothesis TEXT NOT NULL,
            domain TEXT NOT NULL,
            task_class TEXT NOT NULL,
            target_agent_id TEXT,
            target_capability_id TEXT,
            target_skill_id TEXT,
            baseline_version TEXT,
            candidate_version TEXT,
            source_episode_ids TEXT NOT NULL DEFAULT '[]',
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            contradiction_check TEXT NOT NULL DEFAULT '{}',
            implementation_ref TEXT,
            acceptance_criteria TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'CANDIDATE',
            created_at TEXT NOT NULL,
            promoted_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_learning_candidates_status
        ON harness_learning_candidates(status, candidate_type);

        CREATE TABLE IF NOT EXISTS harness_improvement_evaluations (
            evaluation_id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL,
            baseline_metrics TEXT NOT NULL,
            candidate_metrics TEXT NOT NULL,
            trials INTEGER NOT NULL,
            regression_pass INTEGER NOT NULL,
            adversarial_pass INTEGER NOT NULL,
            critical_regression INTEGER NOT NULL DEFAULT 0,
            evaluation_mode TEXT NOT NULL DEFAULT 'LEGACY',
            regression_evidence TEXT NOT NULL DEFAULT '{}',
            adversarial_evidence TEXT NOT NULL DEFAULT '{}',
            observed_evidence TEXT NOT NULL DEFAULT '{}',
            decision TEXT NOT NULL,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            FOREIGN KEY (candidate_id)
                REFERENCES harness_learning_candidates(candidate_id)
                ON DELETE RESTRICT
        );

        CREATE INDEX IF NOT EXISTS idx_improvement_evaluations_candidate
        ON harness_improvement_evaluations(candidate_id);

        CREATE TABLE IF NOT EXISTS harness_skill_versions (
            skill_id TEXT NOT NULL,
            version TEXT NOT NULL,
            parent_version TEXT,
            content_ref TEXT NOT NULL,
            checksum TEXT NOT NULL,
            status TEXT NOT NULL,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            promoted_at TEXT,
            PRIMARY KEY (skill_id, version)
        );

        CREATE TABLE IF NOT EXISTS harness_policy_versions (
            policy_id TEXT NOT NULL,
            version TEXT NOT NULL,
            parent_version TEXT,
            content_ref TEXT NOT NULL,
            checksum TEXT NOT NULL,
            status TEXT NOT NULL,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            promoted_at TEXT,
            PRIMARY KEY (policy_id, version)
        );

        CREATE TABLE IF NOT EXISTS harness_human_corrections (
            correction_id TEXT PRIMARY KEY,
            goal_id TEXT,
            task_id TEXT,
            context TEXT NOT NULL,
            undesired_behavior TEXT NOT NULL,
            desired_behavior TEXT NOT NULL,
            affected_agent TEXT,
            affected_capability TEXT,
            affected_skill TEXT,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            metadata TEXT NOT NULL DEFAULT '{}',
            scope TEXT NOT NULL DEFAULT 'LOCAL',
            status TEXT NOT NULL DEFAULT 'CANDIDATE',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_harness_human_corrections_retrieval
        ON harness_human_corrections(status, affected_capability, affected_skill);

        CREATE TABLE IF NOT EXISTS harness_improvement_missions (
            improvement_mission_id TEXT PRIMARY KEY,
            trigger_type TEXT NOT NULL,
            trigger_refs TEXT NOT NULL DEFAULT '[]',
            diagnosis TEXT NOT NULL,
            hypothesis TEXT NOT NULL,
            evidence_considered TEXT NOT NULL DEFAULT '[]',
            affected_capability TEXT,
            affected_config TEXT,
            objective TEXT,
            constraints TEXT NOT NULL DEFAULT '[]',
            acceptance_criteria TEXT NOT NULL DEFAULT '{}',
            candidate_id TEXT,
            harness_decision_id TEXT NOT NULL,
            authorization_id TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            finished_at TEXT,
            FOREIGN KEY (candidate_id)
                REFERENCES harness_learning_candidates(candidate_id)
                ON DELETE SET NULL
        );
        """
    )

    # Existing databases already contain the Learning Plane tables. Keep this
    # migration additive so operational evidence can be introduced without
    # resetting or rewriting the 14 prior learning commits/data.
    additive_columns = {
        "harness_episodes": {
            "lineage": "TEXT NOT NULL DEFAULT '{}'",
        },
        "harness_memories": {
            "metadata": "TEXT NOT NULL DEFAULT '{}'",
        },
        "harness_learning_candidates": {
            "implementation_ref": "TEXT",
            "acceptance_criteria": "TEXT NOT NULL DEFAULT '{}'",
        },
        "harness_improvement_evaluations": {
            "evaluation_mode": "TEXT NOT NULL DEFAULT 'LEGACY'",
            "regression_evidence": "TEXT NOT NULL DEFAULT '{}'",
            "adversarial_evidence": "TEXT NOT NULL DEFAULT '{}'",
            "observed_evidence": "TEXT NOT NULL DEFAULT '{}'",
        },
        "harness_human_corrections": {
            "metadata": "TEXT NOT NULL DEFAULT '{}'",
        },
        "harness_improvement_missions": {
            "evidence_considered": "TEXT NOT NULL DEFAULT '[]'",
            "affected_capability": "TEXT",
            "affected_config": "TEXT",
            "objective": "TEXT",
            "constraints": "TEXT NOT NULL DEFAULT '[]'",
            "acceptance_criteria": "TEXT NOT NULL DEFAULT '{}'",
        },
    }
    for table, additions in additive_columns.items():
        existing = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for column, declaration in additions.items():
            if column not in existing:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {declaration}"
                )




def _migrate_e2e_stage_checkpoints(connection) -> None:
    """Persist resumable, provenance-preserving checkpoints in the canonical SQLite DB."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS e2e_stage_checkpoints (
            checkpoint_id TEXT PRIMARY KEY,
            pipeline_id TEXT NOT NULL,
            goal_id TEXT NOT NULL,
            stage_id TEXT NOT NULL,
            input_fingerprint TEXT NOT NULL,
            output_hash TEXT NOT NULL,
            output_payload TEXT NOT NULL DEFAULT '{}',
            code_version TEXT NOT NULL,
            contract_version TEXT NOT NULL,
            provider_profile_version TEXT,
            freshness TEXT NOT NULL DEFAULT '{}',
            provenance TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL,
            duration_ms REAL NOT NULL DEFAULT 0,
            source_run_id TEXT,
            source_execution_id TEXT,
            completed_at TEXT NOT NULL,
            invalidated_at TEXT,
            invalidation_reason TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_e2e_stage_checkpoints_goal_stage
        ON e2e_stage_checkpoints(goal_id, stage_id, completed_at DESC);

        CREATE INDEX IF NOT EXISTS idx_e2e_stage_checkpoints_status
        ON e2e_stage_checkpoints(status, completed_at DESC);

        CREATE INDEX IF NOT EXISTS idx_e2e_stage_checkpoints_pipeline
        ON e2e_stage_checkpoints(pipeline_id, goal_id, status);
        """
    )


def _migrate_agent_execution_leases(connection) -> None:
    """Persist Harness-authorized bounded delegation and event-driven task state."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS agent_office_missions (
            mission_id TEXT PRIMARY KEY,
            goal_id TEXT NOT NULL,
            harness_decision_id TEXT NOT NULL,
            authorization_id TEXT NOT NULL,
            execution_id TEXT NOT NULL,
            base_sha TEXT NOT NULL,
            status TEXT NOT NULL,
            request_payload TEXT NOT NULL DEFAULT '{}',
            result_payload TEXT,
            reduction_payload TEXT,
            claimed_by TEXT,
            claimed_at TEXT,
            ready_for_reduction_at TEXT,
            completed_at TEXT,
            error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_agent_office_missions_status
        ON agent_office_missions(status, created_at);

        CREATE INDEX IF NOT EXISTS idx_agent_office_missions_authorization
        ON agent_office_missions(authorization_id, execution_id);

        CREATE TABLE IF NOT EXISTS agent_office_mission_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mission_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (mission_id)
                REFERENCES agent_office_missions(mission_id)
                ON DELETE RESTRICT
        );

        CREATE INDEX IF NOT EXISTS idx_agent_office_mission_events_mission
        ON agent_office_mission_events(mission_id, id);

        CREATE TABLE IF NOT EXISTS agent_execution_leases (
            delegation_id TEXT PRIMARY KEY,
            mission_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            goal_id TEXT NOT NULL,
            harness_decision_id TEXT NOT NULL,
            authorization_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            capability_ids TEXT NOT NULL DEFAULT '[]',
            base_sha TEXT NOT NULL,
            allowed_paths TEXT NOT NULL DEFAULT '[]',
            allowed_tools TEXT NOT NULL DEFAULT '[]',
            allowed_actions TEXT NOT NULL DEFAULT '[]',
            forbidden_actions TEXT NOT NULL DEFAULT '[]',
            input_artifact_refs TEXT NOT NULL DEFAULT '[]',
            expected_outputs TEXT NOT NULL DEFAULT '[]',
            acceptance_criteria TEXT NOT NULL DEFAULT '[]',
            evidence_requirements TEXT NOT NULL DEFAULT '[]',
            time_budget_seconds INTEGER NOT NULL,
            cost_budget REAL NOT NULL,
            tool_call_budget INTEGER NOT NULL,
            retry_budget INTEGER NOT NULL,
            max_parallelism INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            escalation_conditions TEXT NOT NULL DEFAULT '[]',
            owned_task_class TEXT NOT NULL,
            role TEXT NOT NULL,
            read_set TEXT NOT NULL DEFAULT '[]',
            write_set TEXT NOT NULL DEFAULT '[]',
            parent_task_id TEXT,
            authority TEXT NOT NULL DEFAULT 'DELEGATED_ONLY',
            canonical_push_authority TEXT NOT NULL DEFAULT 'NONE',
            status TEXT NOT NULL,
            result_ref TEXT,
            result_hash TEXT,
            error TEXT,
            lease_payload TEXT NOT NULL DEFAULT '{}',
            completed_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(mission_id, task_id, authorization_id)
        );

        CREATE INDEX IF NOT EXISTS idx_agent_execution_leases_mission
        ON agent_execution_leases(mission_id, status, task_id);

        CREATE INDEX IF NOT EXISTS idx_agent_execution_leases_authorization
        ON agent_execution_leases(authorization_id, delegation_id);

        CREATE TABLE IF NOT EXISTS agent_execution_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mission_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            delegation_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (delegation_id)
                REFERENCES agent_execution_leases(delegation_id)
                ON DELETE RESTRICT
        );

        CREATE INDEX IF NOT EXISTS idx_agent_execution_events_mission
        ON agent_execution_events(mission_id, id);

        CREATE INDEX IF NOT EXISTS idx_agent_execution_events_task
        ON agent_execution_events(task_id, id);
        """
    )



def _migrate_memory_workspace_plane(connection) -> None:
    """Extend the existing Harness Learning Plane for cross-surface human memory.

    Obsidian remains a projection/input surface only. These canonical tables live
    in the same SQLite authority as HarnessEpisode, harness_memories and competence.
    """

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS harness_human_decisions (
            decision_id TEXT PRIMARY KEY,
            decision_type TEXT NOT NULL,
            source_surface TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            goal_id TEXT,
            task_id TEXT,
            capability_id TEXT,
            agent_id TEXT,
            artifact_ref TEXT,
            content TEXT NOT NULL,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(source_surface, source_ref, decision_type)
        );

        CREATE INDEX IF NOT EXISTS idx_harness_human_decisions_context
        ON harness_human_decisions(goal_id, task_id, capability_id, agent_id);

        CREATE INDEX IF NOT EXISTS idx_harness_human_decisions_artifact
        ON harness_human_decisions(artifact_ref);

        CREATE TABLE IF NOT EXISTS harness_memory_evaluations (
            evaluation_id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            supersedes_memory_id TEXT,
            authority TEXT NOT NULL,
            authorization_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (memory_id)
                REFERENCES harness_memories(memory_id)
                ON DELETE RESTRICT,
            FOREIGN KEY (supersedes_memory_id)
                REFERENCES harness_memories(memory_id)
                ON DELETE RESTRICT
        );

        CREATE INDEX IF NOT EXISTS idx_harness_memory_evaluations_memory
        ON harness_memory_evaluations(memory_id, created_at DESC);
        """
    )


def _migrate_continuous_operation_plane(connection) -> None:
    """Durable operational cursors/scoreboard for event-driven continuous cycles.

    These tables do not replace Knowledge Brain or Learning Plane. They only
    store source fingerprints, cycle observations and claim lineage indexes.
    """

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS continuous_source_state (
            source_key TEXT PRIMARY KEY,
            source_url TEXT NOT NULL,
            source_type TEXT NOT NULL,
            content_fingerprint TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            evidence_ref TEXT NOT NULL,
            etag TEXT,
            last_modified TEXT,
            metadata TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS continuous_cycle_runs (
            cycle_id TEXT PRIMARY KEY,
            trigger_kind TEXT NOT NULL,
            cycle_kind TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            meaningful_delta INTEGER NOT NULL DEFAULT 0,
            source_fetch_count INTEGER NOT NULL DEFAULT 0,
            memory_hit_count INTEGER NOT NULL DEFAULT 0,
            memory_miss_count INTEGER NOT NULL DEFAULT 0,
            failure_memory_preventions INTEGER NOT NULL DEFAULT 0,
            duplicate_work_count INTEGER NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0,
            human_interventions INTEGER NOT NULL DEFAULT 0,
            useful_findings INTEGER NOT NULL DEFAULT 0,
            verified_claims INTEGER NOT NULL DEFAULT 0,
            rejected_claims INTEGER NOT NULL DEFAULT 0,
            superseded_claims INTEGER NOT NULL DEFAULT 0,
            latency_seconds REAL NOT NULL DEFAULT 0,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            metadata TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_continuous_cycle_runs_kind_time
        ON continuous_cycle_runs(cycle_kind, started_at DESC);

        CREATE TABLE IF NOT EXISTS gta6_claim_lineage (
            claim_id INTEGER PRIMARY KEY,
            subject TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_url TEXT NOT NULL,
            source_type TEXT NOT NULL,
            published_at TEXT,
            observed_at TEXT NOT NULL,
            evidence_ref TEXT NOT NULL,
            evidence_class TEXT NOT NULL,
            status_snapshot TEXT NOT NULL,
            supersedes_claim_id INTEGER,
            related_claims TEXT NOT NULL DEFAULT '[]',
            metadata TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (claim_id) REFERENCES memory_claims(id) ON DELETE CASCADE,
            FOREIGN KEY (supersedes_claim_id) REFERENCES memory_claims(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_gta6_claim_lineage_subject
        ON gta6_claim_lineage(subject, observed_at DESC);

        CREATE INDEX IF NOT EXISTS idx_gta6_claim_lineage_source
        ON gta6_claim_lineage(source_id, observed_at DESC);
        """
    )


def _migrate_gta6_autonomous_knowledge_plane(connection) -> None:
    """Extend the existing GTA6 Knowledge Brain with durable autonomous research state.

    Canonical factual identity remains memory_claims + gta6_claim_lineage. These
    tables add source state, raw evidence, entity/graph structure, research
    frontier, novelty/freshness metadata and daily-run observability.
    """

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS gta6_source_registry (
            source_id TEXT PRIMARY KEY,
            url TEXT NOT NULL UNIQUE,
            domain TEXT NOT NULL,
            source_type TEXT NOT NULL,
            authority_class TEXT NOT NULL,
            reliability_score REAL NOT NULL DEFAULT 0.5,
            reliability_history TEXT NOT NULL DEFAULT '[]',
            discovered_at TEXT NOT NULL,
            last_checked_at TEXT,
            last_changed_at TEXT,
            last_success_at TEXT,
            last_failure_at TEXT,
            etag TEXT,
            last_modified TEXT,
            content_hash TEXT,
            refresh_priority INTEGER NOT NULL DEFAULT 50,
            refresh_interval_seconds INTEGER NOT NULL DEFAULT 86400,
            refresh_state TEXT NOT NULL DEFAULT 'DUE',
            active INTEGER NOT NULL DEFAULT 1,
            provenance TEXT NOT NULL DEFAULT '{}',
            metadata TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_gta6_source_registry_due
        ON gta6_source_registry(active, refresh_state, refresh_priority, last_checked_at);

        CREATE INDEX IF NOT EXISTS idx_gta6_source_registry_authority
        ON gta6_source_registry(authority_class, active);

        CREATE TABLE IF NOT EXISTS gta6_raw_evidence (
            evidence_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            url TEXT NOT NULL,
            publication_date TEXT,
            observed_at TEXT NOT NULL,
            excerpt TEXT NOT NULL,
            video_timestamp REAL,
            frame_ref TEXT,
            artifact_ref TEXT,
            content_hash TEXT NOT NULL,
            source_type TEXT NOT NULL,
            provenance TEXT NOT NULL DEFAULT '{}',
            extraction_method TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (source_id)
                REFERENCES gta6_source_registry(source_id)
                ON DELETE RESTRICT
        );

        CREATE INDEX IF NOT EXISTS idx_gta6_raw_evidence_source
        ON gta6_raw_evidence(source_id, observed_at DESC);

        CREATE INDEX IF NOT EXISTS idx_gta6_raw_evidence_hash
        ON gta6_raw_evidence(content_hash);

        CREATE TABLE IF NOT EXISTS gta6_entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            aliases TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            UNIQUE(entity_type, canonical_name)
        );

        CREATE INDEX IF NOT EXISTS idx_gta6_entities_name
        ON gta6_entities(canonical_name, entity_type);

        CREATE TABLE IF NOT EXISTS gta6_relations (
            relation_id TEXT PRIMARY KEY,
            subject_id TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object_id TEXT NOT NULL,
            claim_id INTEGER,
            evidence_id TEXT,
            confidence REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            observed_at TEXT NOT NULL,
            provenance TEXT NOT NULL DEFAULT '{}',
            metadata TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (subject_id) REFERENCES gta6_entities(entity_id) ON DELETE RESTRICT,
            FOREIGN KEY (object_id) REFERENCES gta6_entities(entity_id) ON DELETE RESTRICT,
            FOREIGN KEY (claim_id) REFERENCES memory_claims(id) ON DELETE SET NULL,
            FOREIGN KEY (evidence_id) REFERENCES gta6_raw_evidence(evidence_id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_gta6_relations_subject
        ON gta6_relations(subject_id, predicate);

        CREATE INDEX IF NOT EXISTS idx_gta6_relations_object
        ON gta6_relations(object_id, predicate);

        CREATE TABLE IF NOT EXISTS gta6_research_frontier (
            question_id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            topic TEXT,
            entity_ids TEXT NOT NULL DEFAULT '[]',
            priority INTEGER NOT NULL DEFAULT 50,
            current_confidence REAL NOT NULL DEFAULT 0.0,
            supporting_evidence TEXT NOT NULL DEFAULT '[]',
            contradictory_evidence TEXT NOT NULL DEFAULT '[]',
            missing_evidence TEXT NOT NULL DEFAULT '[]',
            next_research_strategy TEXT,
            sources_to_watch TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            last_checked_at TEXT,
            status TEXT NOT NULL DEFAULT 'OPEN',
            metadata TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_gta6_research_frontier_priority
        ON gta6_research_frontier(status, priority DESC, last_checked_at);

        CREATE TABLE IF NOT EXISTS gta6_claim_metadata (
            claim_id INTEGER PRIMARY KEY,
            subject_entity_id TEXT,
            predicate TEXT,
            object_entity_id TEXT,
            brain_status TEXT NOT NULL DEFAULT 'DISCOVERED',
            first_seen_at TEXT NOT NULL,
            last_verified_at TEXT,
            superseded_by_claim_id INTEGER,
            related_claims TEXT NOT NULL DEFAULT '[]',
            used_in_content TEXT NOT NULL DEFAULT '[]',
            world_novelty TEXT NOT NULL DEFAULT 'UNKNOWN',
            knowledge_novelty TEXT NOT NULL DEFAULT 'UNKNOWN',
            editorial_novelty TEXT NOT NULL DEFAULT 'UNUSED',
            freshness_class TEXT NOT NULL DEFAULT 'MEDIUM',
            freshness_due_at TEXT,
            consolidated_key TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (claim_id) REFERENCES memory_claims(id) ON DELETE CASCADE,
            FOREIGN KEY (subject_entity_id) REFERENCES gta6_entities(entity_id) ON DELETE SET NULL,
            FOREIGN KEY (object_entity_id) REFERENCES gta6_entities(entity_id) ON DELETE SET NULL,
            FOREIGN KEY (superseded_by_claim_id) REFERENCES memory_claims(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_gta6_claim_metadata_status
        ON gta6_claim_metadata(brain_status, freshness_due_at);

        CREATE INDEX IF NOT EXISTS idx_gta6_claim_metadata_novelty
        ON gta6_claim_metadata(world_novelty, knowledge_novelty, editorial_novelty);

        CREATE TABLE IF NOT EXISTS gta6_brain_daily_runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            sources_checked INTEGER NOT NULL DEFAULT 0,
            sources_changed INTEGER NOT NULL DEFAULT 0,
            new_sources INTEGER NOT NULL DEFAULT 0,
            new_claims INTEGER NOT NULL DEFAULT 0,
            verified_claims INTEGER NOT NULL DEFAULT 0,
            contradicted_claims INTEGER NOT NULL DEFAULT 0,
            superseded_claims INTEGER NOT NULL DEFAULT 0,
            duplicates_avoided INTEGER NOT NULL DEFAULT 0,
            open_questions INTEGER NOT NULL DEFAULT 0,
            resolved_questions INTEGER NOT NULL DEFAULT 0,
            obsidian_notes_updated INTEGER NOT NULL DEFAULT 0,
            retrieval_context_bytes INTEGER NOT NULL DEFAULT 0,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            metadata TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_gta6_brain_daily_runs_time
        ON gta6_brain_daily_runs(started_at DESC);
        """
    )




def _migrate_persistent_intelligence_force(connection) -> None:
    """Persist bounded persistent responsibilities without creating a second authority plane."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS persistent_responsibility_revisions (
            responsibility_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(responsibility_id, revision)
        );

        CREATE TABLE IF NOT EXISTS persistent_responsibility_heads (
            responsibility_id TEXT PRIMARY KEY,
            current_revision INTEGER NOT NULL,
            status TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_persistent_responsibility_state
        ON persistent_responsibility_heads(status, enabled, updated_at);

        CREATE TABLE IF NOT EXISTS persistent_agent_identities (
            persistent_agent_id TEXT NOT NULL,
            responsibility_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            agent_instance_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            runtime_family TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            environment_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(persistent_agent_id, revision)
        );

        CREATE INDEX IF NOT EXISTS idx_persistent_agent_responsibility
        ON persistent_agent_identities(responsibility_id, revision DESC);

        CREATE INDEX IF NOT EXISTS idx_persistent_agent_session
        ON persistent_agent_identities(session_id);

        CREATE TABLE IF NOT EXISTS persistent_agent_activity (
            activity_id TEXT PRIMARY KEY,
            responsibility_id TEXT NOT NULL,
            persistent_agent_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            task_id TEXT,
            mission_id TEXT,
            summary TEXT NOT NULL,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            payload_digest TEXT NOT NULL,
            schema_name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_persistent_activity_feed
        ON persistent_agent_activity(responsibility_id, occurred_at, activity_id);

        CREATE INDEX IF NOT EXISTS idx_persistent_activity_type
        ON persistent_agent_activity(event_type, occurred_at);

        CREATE TABLE IF NOT EXISTS persistent_work_usage (
            responsibility_id TEXT NOT NULL,
            usage_date TEXT NOT NULL,
            active_seconds INTEGER NOT NULL DEFAULT 0,
            agent_turns INTEGER NOT NULL DEFAULT 0,
            semantic_calls INTEGER NOT NULL DEFAULT 0,
            provider_calls INTEGER NOT NULL DEFAULT 0,
            tool_calls INTEGER NOT NULL DEFAULT 0,
            subagents INTEGER NOT NULL DEFAULT 0,
            subagent_seconds INTEGER NOT NULL DEFAULT 0,
            retries INTEGER NOT NULL DEFAULT 0,
            external_tool_seconds INTEGER NOT NULL DEFAULT 0,
            cost REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(responsibility_id, usage_date)
        );

        CREATE TABLE IF NOT EXISTS persistent_responsibility_wakes (
            wake_id TEXT PRIMARY KEY,
            responsibility_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            wake_reason TEXT NOT NULL,
            wake_source TEXT NOT NULL,
            wake_event_ref TEXT NOT NULL,
            wake_timestamp TEXT NOT NULL,
            event_digest TEXT NOT NULL,
            processed_state TEXT NOT NULL,
            opportunity_ref TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(responsibility_id, wake_source, wake_event_ref)
        );

        CREATE INDEX IF NOT EXISTS idx_persistent_wake_responsibility
        ON persistent_responsibility_wakes(responsibility_id, wake_timestamp, wake_id);

        CREATE TABLE IF NOT EXISTS persistent_wake_usage (
            wake_id TEXT PRIMARY KEY,
            responsibility_id TEXT NOT NULL,
            active_seconds INTEGER NOT NULL DEFAULT 0,
            agent_turns INTEGER NOT NULL DEFAULT 0,
            semantic_calls INTEGER NOT NULL DEFAULT 0,
            provider_calls INTEGER NOT NULL DEFAULT 0,
            tool_calls INTEGER NOT NULL DEFAULT 0,
            subagents INTEGER NOT NULL DEFAULT 0,
            subagent_seconds INTEGER NOT NULL DEFAULT 0,
            retries INTEGER NOT NULL DEFAULT 0,
            external_tool_seconds INTEGER NOT NULL DEFAULT 0,
            cost REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS persistent_opportunity_candidates (
            candidate_id TEXT PRIMARY KEY,
            responsibility_id TEXT NOT NULL,
            wake_id TEXT NOT NULL UNIQUE,
            candidate_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            content_digest TEXT NOT NULL,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_persistent_opportunity_responsibility
        ON persistent_opportunity_candidates(responsibility_id, created_at, candidate_id);

        CREATE TABLE IF NOT EXISTS persistent_agent_custom_rule_revisions (
            rule_id TEXT NOT NULL,
            responsibility_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            effect TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT NOT NULL,
            risk_class TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(rule_id, revision)
        );

        CREATE TABLE IF NOT EXISTS persistent_agent_custom_rule_heads (
            rule_id TEXT PRIMARY KEY,
            responsibility_id TEXT NOT NULL,
            current_revision INTEGER NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_persistent_custom_rule_responsibility
        ON persistent_agent_custom_rule_heads(responsibility_id, status, rule_id);
        """
    )

def _migrate_youtube_intelligence_revenue_plane(connection) -> None:
    """Persist typed YouTube intelligence/business evidence without creating a second authority plane."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS youtube_intelligence_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id TEXT NOT NULL UNIQUE,
            schema_name TEXT NOT NULL,
            subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            period_start TEXT,
            period_end TEXT,
            payload_json TEXT NOT NULL,
            content_digest TEXT NOT NULL,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            authority TEXT NOT NULL DEFAULT 'DEEPSEEK_HARNESS',
            source_system TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            supersedes_record_id TEXT,
            retrieved_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_youtube_intelligence_schema_subject
        ON youtube_intelligence_records(schema_name, subject_type, subject_id, created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_youtube_intelligence_period
        ON youtube_intelligence_records(schema_name, period_start, period_end);

        CREATE INDEX IF NOT EXISTS idx_youtube_intelligence_digest
        ON youtube_intelligence_records(content_digest);

        CREATE TABLE IF NOT EXISTS youtube_quota_budget (
            api TEXT NOT NULL,
            operation TEXT NOT NULL,
            budget_date TEXT NOT NULL,
            estimated_unit_cost INTEGER NOT NULL,
            consumed INTEGER NOT NULL DEFAULT 0,
            hard_limit INTEGER,
            priority INTEGER NOT NULL DEFAULT 50,
            cache_state TEXT NOT NULL DEFAULT 'UNKNOWN',
            last_request_digest TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(api, operation, budget_date)
        );

        CREATE TABLE IF NOT EXISTS youtube_revenue_ledger (
            entry_id TEXT PRIMARY KEY,
            video_id TEXT,
            publication_id INTEGER,
            revenue_class TEXT NOT NULL,
            source_label TEXT NOT NULL,
            amount REAL,
            currency TEXT,
            amount_status TEXT NOT NULL,
            period_start TEXT,
            period_end TEXT,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            content_digest TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_youtube_revenue_ledger_video
        ON youtube_revenue_ledger(video_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS youtube_external_operations (
            operation_id TEXT PRIMARY KEY,
            capability_id TEXT NOT NULL,
            authorization_ref TEXT NOT NULL,
            operation TEXT NOT NULL,
            target TEXT NOT NULL,
            payload_digest TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            state TEXT NOT NULL,
            remote_receipt TEXT NOT NULL DEFAULT '{}',
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(authorization_ref, operation, target, payload_digest)
        );

        CREATE INDEX IF NOT EXISTS idx_youtube_external_operations_state
        ON youtube_external_operations(state, created_at);

        CREATE TABLE IF NOT EXISTS youtube_reporting_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            report_id TEXT NOT NULL,
            report_type TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            revision INTEGER NOT NULL,
            backfill_state TEXT NOT NULL,
            content_digest TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(report_id, period_start, period_end, revision, content_digest)
        );

        CREATE INDEX IF NOT EXISTS idx_youtube_reporting_period
        ON youtube_reporting_snapshots(report_type, period_start, period_end, revision DESC);
        """
    )

    quota_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(youtube_quota_budget)").fetchall()
    }
    for column_name, column_sql in (
        ("quota_bucket", "TEXT"),
        ("policy_id", "TEXT"),
        ("policy_digest", "TEXT"),
        ("reset_time", "TEXT"),
        ("pagination_cost", "INTEGER NOT NULL DEFAULT 1"),
    ):
        if column_name not in quota_columns:
            connection.execute(
                f"ALTER TABLE youtube_quota_budget ADD COLUMN {column_name} {column_sql}"
            )


def _migrate_openai_agents_dd2(connection) -> None:
    """Persist subordinate OpenAI Agents sessions without granting mission authority."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS openai_agent_session_receipts (
            session_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            turn_id TEXT,
            environment_id TEXT,
            agent_model TEXT NOT NULL,
            reasoning_effort TEXT NOT NULL,
            state TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            content_digest TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(session_id, revision)
        );

        CREATE INDEX IF NOT EXISTS idx_openai_agent_session_turn
        ON openai_agent_session_receipts(session_id, turn_id, revision DESC);

        CREATE INDEX IF NOT EXISTS idx_openai_agent_session_state
        ON openai_agent_session_receipts(state, updated_at);

        CREATE TABLE IF NOT EXISTS openai_agent_session_heads (
            session_id TEXT PRIMARY KEY,
            current_revision INTEGER NOT NULL,
            latest_turn_id TEXT,
            state TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS openai_agent_tool_results (
            session_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            call_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            success INTEGER NOT NULL,
            output_json TEXT NOT NULL,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            result_digest TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(session_id, turn_id, call_id)
        );

        CREATE INDEX IF NOT EXISTS idx_openai_agent_tool_result_digest
        ON openai_agent_tool_results(result_digest);

        CREATE TABLE IF NOT EXISTS openai_agent_environment_leases (
            lease_id TEXT PRIMARY KEY,
            environment_type TEXT NOT NULL,
            environment_id TEXT NOT NULL,
            task_lease_ref TEXT NOT NULL,
            status TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_openai_environment_task
        ON openai_agent_environment_leases(task_lease_ref, status, expires_at);

        CREATE TABLE IF NOT EXISTS openai_sprite_environment_bindings (
            binding_id TEXT PRIMARY KEY,
            environment_lease_id TEXT NOT NULL,
            mission_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            openai_session_id TEXT NOT NULL,
            openai_environment_id TEXT NOT NULL,
            sprite_id TEXT NOT NULL,
            sprite_name TEXT NOT NULL,
            workspace TEXT NOT NULL,
            repo_sha TEXT NOT NULL,
            tree_sha TEXT NOT NULL,
            checkpoint_id TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            workspace_digest TEXT,
            executor_credential_ref TEXT,
            payload_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_openai_sprite_binding_session
        ON openai_sprite_environment_bindings(
            openai_session_id, task_id, attempt_id, status
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_openai_sprite_one_active_compute
        ON openai_sprite_environment_bindings(
            openai_session_id, task_id, attempt_id
        )
        WHERE status='ACTIVE';
        """
    )

    receipt_columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(openai_agent_session_receipts)"
        ).fetchall()
    }
    if "content_digest" not in receipt_columns:
        connection.execute(
            "ALTER TABLE openai_agent_session_receipts ADD COLUMN content_digest TEXT"
        )

    head_columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(openai_agent_session_heads)"
        ).fetchall()
    }
    if "latest_turn_id" not in head_columns:
        connection.execute(
            "ALTER TABLE openai_agent_session_heads ADD COLUMN latest_turn_id TEXT"
        )
        if "turn_id" in head_columns:
            connection.execute(
                "UPDATE openai_agent_session_heads SET latest_turn_id=turn_id "
                "WHERE latest_turn_id IS NULL"
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
        _migrate_youtube_publication_cloud_execution(connection)
        _migrate_youtube_content_packages(connection)
        _migrate_youtube_intelligence_revenue_plane(connection)
        _migrate_persistent_intelligence_force(connection)
        _migrate_openai_agents_dd2(connection)
        _migrate_content_segment_asset_identity(connection)
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
        _migrate_production_plans(connection)
        _migrate_gta6_media_intelligence(connection)
        _migrate_harness_authorizations(connection)
        _migrate_trusted_security_review_receipts(connection)
        _migrate_harness_learning_plane(connection)
        _migrate_memory_workspace_plane(connection)
        _migrate_continuous_operation_plane(connection)
        _migrate_gta6_autonomous_knowledge_plane(connection)
        _migrate_agent_execution_leases(connection)
        _migrate_e2e_stage_checkpoints(connection)
        connection.commit()
    finally:
        connection.close()
