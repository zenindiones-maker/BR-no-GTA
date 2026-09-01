from typing import Any

from app.services.google_youtube_publisher_factory import (
    create_google_youtube_publisher,
)
from app.services.youtube_publication_orchestration import (
    publish_youtube_publication,
)


def publish_youtube_publication_with_google(
    *,
    publication_id: int,
    token_file: str,
) -> dict[str, Any]:
    """
    Publica uma YouTube Publication usando o Publisher real do Google.

    Responsabilidades:
    1. Compor o GoogleYouTubePublisher através da Factory.
    2. Entregar o Publisher para a orquestração.
    3. Retornar o resultado da orquestração.

    Esta função não:
    - executa OAuth;
    - abre navegador;
    - carrega Credentials diretamente;
    - constrói o cliente Google;
    - executa upload diretamente;
    - acessa SQLite;
    - altera o estado da publicação diretamente.
    """

    if publication_id is None:
        raise ValueError("publication_id is required")

    if not isinstance(token_file, str) or not token_file.strip():
        raise ValueError("token_file is required")

    publisher = create_google_youtube_publisher(
        token_file=token_file,
    )

    return publish_youtube_publication(
        publication_id,
        publisher,
    )
