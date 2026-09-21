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
        _migrate_harness_learning_plane(connection)
        _migrate_memory_workspace_plane(connection)
        _migrate_continuous_operation_plane(connection)
        _migrate_agent_execution_leases(connection)
        _migrate_e2e_stage_checkpoints(connection)
        connection.commit()
    finally:
        connection.close()
