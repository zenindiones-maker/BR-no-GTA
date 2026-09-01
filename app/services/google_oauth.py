from pathlib import Path
from typing import Any, Callable

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
    Não executa autorização.
    """

    if not isinstance(client_secrets_file, str):
        raise ValueError(
            "client_secrets_file is required"
        )

    if not client_secrets_file.strip():
        raise ValueError(
            "client_secrets_file is required"
        )

    path = Path(client_secrets_file)

    if not path.is_file():
        raise ValueError(
            f"client secrets file not found: {client_secrets_file}"
        )

    return InstalledAppFlow.from_client_secrets_file(
        str(path),
        scopes=[YOUTUBE_UPLOAD_SCOPE],
    )


def authorize_youtube(
    *,
    client_secrets_file: str,
    authorization_runner: Callable[[Any], Any] | None = None,
) -> Any:
    """
    Executa a autorização OAuth e retorna as credenciais.

    O executor de autorização é injetável para permitir testes
    sem navegador, rede ou interação humana.

    Se nenhum executor for fornecido, utiliza o fluxo padrão
    disponibilizado pelo InstalledAppFlow.
    """

    flow = create_oauth_flow(
        client_secrets_file=client_secrets_file,
    )

    if authorization_runner is not None:
        credentials = authorization_runner(flow)
    else:
        credentials = flow.run_local_server(
            port=0,
            access_type="offline",
            prompt="consent",
        )

    if credentials is None:
        raise RuntimeError(
            "OAuth authorization did not return credentials"
        )

    return credentials
