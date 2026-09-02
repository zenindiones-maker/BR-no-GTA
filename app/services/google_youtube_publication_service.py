from typing import Any, Callable

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
    client_secrets_file: str,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Publica uma YouTube Publication usando o Publisher real do Google.

    Responsabilidades:
    1. Validar as entradas necessárias à composição.
    2. Compor o GoogleYouTubePublisher através da Factory.
    3. Entregar o Publisher para a orquestração.
    4. Retornar o resultado da orquestração.

    A aquisição das credenciais permanece delegada à Factory,
    que utiliza get_youtube_credentials().

    Esta função não:
    - implementa OAuth;
    - abre navegador;
    - carrega Credentials diretamente;
    - constrói o cliente Google diretamente;
    - executa upload diretamente;
    - acessa SQLite;
    - altera o estado da publicação diretamente.
    """

    if publication_id is None:
        raise ValueError("publication_id is required")

    if not isinstance(token_file, str) or not token_file.strip():
        raise ValueError("token_file is required")

    if (
        not isinstance(client_secrets_file, str)
        or not client_secrets_file.strip()
    ):
        raise ValueError("client_secrets_file is required")

    publisher = create_google_youtube_publisher(
        token_file=token_file,
        client_secrets_file=client_secrets_file,
        authorization_runner=authorization_runner,
        request=request,
    )

    return publish_youtube_publication(
        publication_id,
        publisher,
    )
