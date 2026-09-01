from typing import Any

from google_auth_oauthlib.flow import InstalledAppFlow


YOUTUBE_UPLOAD_SCOPE = (
    "https://www.googleapis.com/auth/youtube.upload"
)


def create_oauth_flow(
    *,
    client_secrets_file: str,
) -> Any:
    """
    Cria o fluxo OAuth do Google para acesso ao YouTube.

    Esta função apenas prepara o fluxo.
    Não abre navegador e não executa autorização.

    Responsabilidade:
        client_secrets.json + scopes
            -> InstalledAppFlow
    """

    if not isinstance(client_secrets_file, str):
        raise ValueError(
            "client_secrets_file is required"
        )

    if not client_secrets_file.strip():
        raise ValueError(
            "client_secrets_file is required"
        )

    return InstalledAppFlow.from_client_secrets_file(
        client_secrets_file,
        scopes=[YOUTUBE_UPLOAD_SCOPE],
    )
