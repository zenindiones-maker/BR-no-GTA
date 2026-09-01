from app.services.google_oauth import load_youtube_credentials
from app.services.google_youtube_client import create_youtube_service
from app.services.google_youtube_publisher import GoogleYouTubePublisher


def create_google_youtube_publisher(
    *,
    token_file: str,
) -> GoogleYouTubePublisher:
    """
    Compõe o Publisher real do YouTube a partir das dependências Google.

    Fluxo:

        token_file
            ↓
        load_youtube_credentials()
            ↓
        Credentials
            ↓
        create_youtube_service()
            ↓
        YouTube Service
            ↓
        GoogleYouTubePublisher

    Esta função somente compõe as dependências.

    Não é responsabilidade desta função:
    - executar OAuth;
    - abrir navegador;
    - fazer upload;
    - acessar SQLite;
    - alterar YouTube Publication;
    - executar publish().
    """

    if not isinstance(token_file, str) or not token_file.strip():
        raise ValueError("token_file is required")

    credentials = load_youtube_credentials(
        token_file=token_file,
    )

    youtube_service = create_youtube_service(
        credentials,
    )

    return GoogleYouTubePublisher(
        youtube_service=youtube_service,
    )
