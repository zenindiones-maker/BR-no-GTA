from typing import Any, Callable

from app.services.google_oauth import get_youtube_credentials
from app.services.google_youtube_client import create_youtube_service
from app.services.google_youtube_publisher import GoogleYouTubePublisher


def create_google_youtube_publisher(
    *,
    token_file: str,
    client_secrets_file: str,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> GoogleYouTubePublisher:
    """
    Compõe o Publisher real do YouTube a partir das dependências Google.

    Fluxo:

        token_file
        client_secrets_file
            ↓
        get_youtube_credentials()
            ↓
        Credentials
            ↓
        create_youtube_service()
            ↓
        YouTube Service
            ↓
        GoogleYouTubePublisher

    Esta função somente compõe as dependências.

    A aquisição das credenciais permanece delegada a
    get_youtube_credentials().

    Não é responsabilidade desta função:
    - implementar OAuth;
    - executar upload;
    - acessar SQLite;
    - alterar YouTube Publication;
    - executar publish();
    - implementar refresh de credenciais;
    - persistir credenciais diretamente.
    """

    if not isinstance(token_file, str) or not token_file.strip():
        raise ValueError("token_file is required")

    if (
        not isinstance(client_secrets_file, str)
        or not client_secrets_file.strip()
    ):
        raise ValueError("client_secrets_file is required")

    credentials = get_youtube_credentials(
        token_file=token_file,
        client_secrets_file=client_secrets_file,
        authorization_runner=authorization_runner,
        request=request,
    )

    youtube_service = create_youtube_service(
        credentials,
    )

    return GoogleYouTubePublisher(
        youtube_service=youtube_service,
    )
