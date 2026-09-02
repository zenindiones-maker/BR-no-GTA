import sqlite3

from app.database.schema import _migrate_youtube_publication_file_path


def _create_legacy_youtube_publications_table(connection):
    connection.execute(
        """
        CREATE TABLE youtube_publications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL UNIQUE,
            content_item_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]',
            category_id TEXT NOT NULL,
            privacy_status TEXT NOT NULL DEFAULT 'private',
            publish_at TEXT,
            youtube_video_id TEXT,
            youtube_url TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            published_at TEXT
        )
        """
    )


def _get_columns(connection):
    return {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(youtube_publications)"
        ).fetchall()
    }


def test_migration_adds_file_path_to_legacy_database():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row

    try:
        _create_legacy_youtube_publications_table(connection)

        columns_before = _get_columns(connection)

        assert "file_path" not in columns_before

        _migrate_youtube_publication_file_path(connection)

        columns_after = _get_columns(connection)

        assert "file_path" in columns_after
    finally:
        connection.close()


def test_migration_is_idempotent():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row

    try:
        _create_legacy_youtube_publications_table(connection)

        _migrate_youtube_publication_file_path(connection)
        columns_after_first_run = _get_columns(connection)

        _migrate_youtube_publication_file_path(connection)
        columns_after_second_run = _get_columns(connection)

        assert "file_path" in columns_after_first_run
        assert columns_after_second_run == columns_after_first_run
    finally:
        connection.close()


def test_file_path_is_nullable_for_legacy_records():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row

    try:
        _create_legacy_youtube_publications_table(connection)

        _migrate_youtube_publication_file_path(connection)

        connection.execute(
            """
            INSERT INTO youtube_publications (
                video_id,
                content_item_id,
                title,
                category_id
            )
            VALUES (?, ?, ?, ?)
            """,
            (1, 1, "Legacy publication", "20"),
        )
        connection.commit()

        row = connection.execute(
            """
            SELECT file_path
            FROM youtube_publications
            WHERE video_id = ?
            """,
            (1,),
        ).fetchone()

        assert row["file_path"] is None
    finally:
        connection.close()
