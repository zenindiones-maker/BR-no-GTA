from pathlib import Path

path = Path("app/database/schema.py")
text = path.read_text(encoding="utf-8")
anchor = '''def _migrate_media_knowledge(connection) -> None:
'''
insert = '''def _migrate_youtube_publication_cloud_execution(connection) -> None:
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


'''
assert text.count(anchor) == 1, "expected media knowledge migration anchor"
text = text.replace(anchor, insert + anchor)
call = '''        _migrate_youtube_publication_file_path(connection)\n'''
replacement = call + '''        _migrate_youtube_publication_cloud_execution(connection)\n'''
assert text.count(call) == 1, "expected YouTube file_path migration call"
text = text.replace(call, replacement)
path.write_text(text, encoding="utf-8")
