from typing import Any

from googleapiclient.discovery import build


YOUTUBE_UPLOAD_SCOPE = (
    "https://www.googleapis.com/auth/youtube.upload"
)


def build_youtube_service(
    *,
    credentials: Any,
) -> Any:
    """
    Cria o cliente da YouTube Data API v3 usando
    credenciais OAuth já obtidas.

    Esta função NÃO executa o fluxo OAuth.

    Recebe:
        credentials
            Credenciais OAuth válidas.

    Retorna:
        Cliente autenticado da YouTube Data API.

    Responsabilidade:
        OAuth credentials -> YouTube API service
    """

    if credentials is None:
        raise ValueError("credentials are required")

    return build(
        "youtube",
        "v3",
        credentials=credentials,
    )
