"""Speech persistence schema must preserve MediaKnowledge lineage."""
from app.database.connection import get_connection
from app.database.schema import initialize_schema


def test_speech_schema_is_idempotent_with_real_foreign_key(monkeypatch, tmp_path):
    monkeypatch.setenv("BR_TEST_DATABASE", str(tmp_path / "speech.sqlite3"))
    initialize_schema()
    initialize_schema()
    conn = get_connection()
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(speech_analysis)")}
        assert {"id", "media_knowledge_id", "source_path", "provider", "model", "payload"} <= columns
        assert any(
            row["table"] == "media_knowledge" and row["from"] == "media_knowledge_id"
            for row in conn.execute("PRAGMA foreign_key_list(speech_analysis)")
        )
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(speech_analysis)")}
        assert "idx_speech_analysis_media_knowledge" in indexes
    finally:
        conn.close()
