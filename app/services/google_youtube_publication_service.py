from typing import Any, Callable

from app.services.google_youtube_configuration import (
    get_youtube_client_secrets_file,
    get_youtube_token_file,
)
from app.services.google_youtube_publisher_factory import (
    create_google_youtube_publisher,
)
from app.services.youtube_publication_orchestration import (
    publish_youtube_publication,
)


def publish_youtube_publication_with_google(
    *,
    publication_id: int,
    token_file: str | None = None,
    client_secrets_file: str | None = None,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Publica uma YouTube Publication usando o Publisher real do Google.

    Os caminhos OAuth são resolvidos pela configuração canônica
    quando não forem fornecidos explicitamente.

    Responsabilidades:
    1. Validar a identificação da publicação.
    2. Resolver a configuração Google/YouTube.
    3. Compor o GoogleYouTubePublisher através da Factory.
    4. Entregar o Publisher para a orquestração.
    5. Retornar o resultado da orquestração.

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

    resolved_token_file = (
        token_file
        if token_file is not None
        else get_youtube_token_file()
    )

    resolved_client_secrets_file = (
        client_secrets_file
        if client_secrets_file is not None
        else get_youtube_client_secrets_file()
    )

    if (
        not isinstance(resolved_token_file, str)
        or not resolved_token_file.strip()
    ):
        raise ValueError("token_file is required")

    if (
        not isinstance(resolved_client_secrets_file, str)
        or not resolved_client_secrets_file.strip()
    ):
        raise ValueError("client_secrets_file is required")

    publisher = create_google_youtube_publisher(
        token_file=resolved_token_file,
        client_secrets_file=resolved_client_secrets_file,
        authorization_runner=authorization_runner,
        request=request,
    )

    return publish_youtube_publication(
        publication_id,
        publisher,
    )
