import json
from typing import Any

from app.database.connection import get_connection


def insert_youtube_publication(
    video_id: int,
    content_item_id: int,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "20",
    privacy_status: str = "private",
    publish_at: str | None = None,
    file_path: str | None = None,
    status: str = "pending",
) -> int:
    """Cria uma publicação destinada ao YouTube."""

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO youtube_publications (
                video_id,
                content_item_id,
                title,
                description,
                tags,
                category_id,
                privacy_status,
                publish_at,
                file_path,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_id,
                content_item_id,
                title,
                description,
                json.dumps(
                    tags or [],
                    ensure_ascii=False,
                ),
                category_id,
                privacy_status,
                publish_at,
                file_path,
                status,
            ),
        )

        connection.commit()

        return int(cursor.lastrowid)

    finally:
        connection.close()


def get_youtube_publication(
    publication_id: int,
) -> dict[str, Any] | None:
    """Busca uma publicação do YouTube pelo ID."""

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                video_id,
                content_item_id,
                title,
                description,
                tags,
                category_id,
                file_path,
                privacy_status,
                publish_at,
                youtube_video_id,
                youtube_url,
                status,
                error,
                created_at,
                updated_at,
                published_at
            FROM youtube_publications
            WHERE id = ?
            """,
            (publication_id,),
        ).fetchone()

        if row is None:
            return None

        publication = dict(row)
        publication["tags"] = json.loads(publication["tags"] or "[]")
        return publication

    finally:
        connection.close()


def get_youtube_publication_by_video_id(
    video_id: int,
) -> dict[str, Any] | None:
    """Busca a publicação YouTube associada a um vídeo."""

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                video_id,
                content_item_id,
                title,
                description,
                tags,
                category_id,
                file_path,
                privacy_status,
                publish_at,
                youtube_video_id,
                youtube_url,
                status,
                error,
                created_at,
                updated_at,
                published_at
            FROM youtube_publications
            WHERE video_id = ?
            """,
            (video_id,),
        ).fetchone()

        if row is None:
            return None

        publication = dict(row)
        publication["tags"] = json.loads(publication["tags"] or "[]")
        return publication

    finally:
        connection.close()



def get_next_pending_youtube_publication() -> dict[str, Any] | None:
    """Busca a próxima publicação YouTube pendente por ordem de criação."""
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT
                id,
                video_id,
                content_item_id,
                title,
                description,
                tags,
                category_id,
                file_path,
                privacy_status,
                publish_at,
                youtube_video_id,
                youtube_url,
                status,
                error,
                created_at,
                updated_at,
                published_at
            FROM youtube_publications
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()

        if row is None:
            return None

        publication = dict(row)
        publication["tags"] = json.loads(publication["tags"] or "[]")
        return publication
    finally:
        connection.close()

def list_youtube_publications() -> list[dict[str, Any]]:
    """Lista todas as publicações destinadas ao YouTube."""

    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                video_id,
                content_item_id,
                title,
                description,
                tags,
                category_id,
                file_path,
                privacy_status,
                publish_at,
                youtube_video_id,
                youtube_url,
                status,
                error,
                created_at,
                updated_at,
                published_at
            FROM youtube_publications
            ORDER BY id ASC
            """
        ).fetchall()

        publications = [dict(row) for row in rows]
        for publication in publications:
            publication["tags"] = json.loads(publication["tags"] or "[]")
        return publications

    finally:
        connection.close()


def update_youtube_publication_status(
    publication_id: int,
    status: str,
    error: str | None = None,
) -> bool:
    """Atualiza o estado operacional da publicação."""

    if not isinstance(publication_id, int) or publication_id <= 0:
        raise ValueError("publication_id must be a positive integer.")

    if status not in {"pending", "published", "failed"}:
        raise ValueError(
            "status must be one of: pending, published, failed."
        )

    if status == "failed":
        if not isinstance(error, str) or not error.strip():
            raise ValueError(
                "error is required when status is failed."
            )
        error = error.strip()
    else:
        error = None

    connection = get_connection()

    try:
        connection.execute("BEGIN")

        row = connection.execute(
            """
            SELECT
                status
            FROM youtube_publications
            WHERE id = ?
            """,
            (publication_id,),
        ).fetchone()

        if row is None:
            connection.rollback()
            return False

        current_status = row["status"]

        if current_status != "pending":
            connection.rollback()
            raise ValueError(
                "YouTube Publication só pode sair de pending: "
                f"status atual = {current_status}"
            )

        cursor = connection.execute(
            """
            UPDATE youtube_publications
            SET
                status = ?,
                error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = 'pending'
            """,
            (
                status,
                error,
                publication_id,
            ),
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return False

        connection.commit()
        return True

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def mark_youtube_uploaded(
    publication_id: int,
    youtube_video_id: str,
    youtube_url: str,
) -> bool:
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE youtube_publications
            SET
                youtube_video_id = ?,
                youtube_url = ?,
                status = 'uploaded',
                error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = 'pending'
            """,
            (
                youtube_video_id,
                youtube_url,
                publication_id,
            ),
        )
        connection.commit()
        return cursor.rowcount == 1
    finally:
        connection.close()


def mark_youtube_published(
    publication_id: int,
    youtube_video_id: str,
    youtube_url: str,
) -> bool:
    """Registra uma publicação efetivamente realizada no YouTube."""

    if not isinstance(publication_id, int) or publication_id <= 0:
        raise ValueError("publication_id must be a positive integer.")

    if not isinstance(youtube_video_id, str) or not youtube_video_id.strip():
        raise ValueError("youtube_video_id is required.")

    if not isinstance(youtube_url, str) or not youtube_url.strip():
        raise ValueError("youtube_url is required.")

    connection = get_connection()

    try:
        connection.execute("BEGIN")

        row = connection.execute(
            """
            SELECT status
            FROM youtube_publications
            WHERE id = ?
            """,
            (publication_id,),
        ).fetchone()

        if row is None:
            connection.rollback()
            return False

        if row["status"] != "uploaded":
            connection.rollback()
            raise ValueError(
                "YouTube Publication só pode ser publicada a partir de "
                "uploaded: "
                f"status atual = {row['status']}"
            )

        cursor = connection.execute(
            """
            UPDATE youtube_publications
            SET
                youtube_video_id = ?,
                youtube_url = ?,
                status = 'published',
                error = NULL,
                published_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = 'uploaded'
            """,
            (
                youtube_video_id,
                youtube_url,
                publication_id,
            ),
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return False

        connection.commit()
        return True

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

def mark_youtube_failed(
    publication_id: int,
    error: str,
) -> bool:
    """Registra uma tentativa de publicação que falhou."""

    if not isinstance(publication_id, int) or publication_id <= 0:
        raise ValueError("publication_id must be a positive integer.")

    if not isinstance(error, str) or not error.strip():
        raise ValueError("error is required.")

    connection = get_connection()

    try:
        connection.execute("BEGIN")

        row = connection.execute(
            """
            SELECT
                status
            FROM youtube_publications
            WHERE id = ?
            """,
            (publication_id,),
        ).fetchone()

        if row is None:
            connection.rollback()
            return False

        if row["status"] != "pending":
            connection.rollback()
            raise ValueError(
                "YouTube Publication só pode falhar a partir de pending: "
                f"status atual = {row['status']}"
            )

        cursor = connection.execute(
            """
            UPDATE youtube_publications
            SET
                status = 'failed',
                error = ?,
                youtube_video_id = NULL,
                youtube_url = NULL,
                published_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = 'pending'
            """,
            (
                error.strip(),
                publication_id,
            ),
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return False

        connection.commit()
        return True

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()
