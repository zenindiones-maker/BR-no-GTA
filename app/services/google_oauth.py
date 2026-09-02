from pathlib import Path
from typing import Any, Callable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


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
        raise ValueError("client_secrets_file is required")

    if not client_secrets_file.strip():
        raise ValueError("client_secrets_file is required")

    path = Path(client_secrets_file)

    if not path.is_file():
        raise ValueError(
            f"client secrets file not found: {client_secrets_file}"
        )

    return InstalledAppFlow.from_client_secrets_file(
        str(path),
        scopes=YOUTUBE_SCOPES,
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


def save_youtube_credentials(
    *,
    credentials: Any,
    token_file: str,
) -> None:
    """
    Persiste as credenciais OAuth em um arquivo JSON.

    O arquivo deve estar fora do versionamento do Git.
    """
    if credentials is None:
        raise ValueError("credentials are required")

    if not isinstance(token_file, str) or not token_file.strip():
        raise ValueError("token_file is required")

    path = Path(token_file)

    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        credentials.to_json(),
        encoding="utf-8",
    )


def load_youtube_credentials(
    *,
    token_file: str,
    request: Any | None = None,
) -> Credentials:
    """
    Carrega credenciais OAuth persistidas.

    Se o access token estiver expirado e existir refresh token,
    renova as credenciais sem nova autorização do usuário.

    Não executa OAuth interativo.
    """
    if not isinstance(token_file, str) or not token_file.strip():
        raise ValueError("token_file is required")

    path = Path(token_file)

    if not path.is_file():
        raise ValueError(
            f"token file not found: {token_file}"
        )

    credentials = Credentials.from_authorized_user_file(
        str(path),
        scopes=YOUTUBE_SCOPES,
    )

    if credentials.valid:
        return credentials

    if credentials.expired and credentials.refresh_token:
        refresh_request = (
            request if request is not None else Request()
        )

        credentials.refresh(refresh_request)

        save_youtube_credentials(
            credentials=credentials,
            token_file=str(path),
        )

        return credentials

    raise RuntimeError(
        "YouTube OAuth credentials are invalid or cannot be refreshed"
    )


def get_youtube_credentials(
    *,
    token_file: str,
    client_secrets_file: str,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> Any:
    """
    Obtém credenciais OAuth do YouTube.

    Estratégia:

    1. Tenta carregar as credenciais persistidas.
    2. Se o token existir e estiver válido, reutiliza.
    3. Se estiver expirado e puder ser renovado, o carregamento
       executa o refresh automaticamente.
    4. Se o token ainda não existir, executa a autorização OAuth.
    5. Persiste as credenciais obtidas pela autorização.
    6. Retorna as credenciais.

    A autorização permanece delegada a authorize_youtube().
    O carregamento e refresh permanecem delegados a
    load_youtube_credentials().

    O authorization_runner e o request existem para permitir
    testes determinísticos sem navegador, rede ou interação humana.
    """
    if not isinstance(token_file, str) or not token_file.strip():
        raise ValueError("token_file is required")

    token_path = Path(token_file)

    if token_path.is_file():
        return load_youtube_credentials(
            token_file=token_file,
            request=request,
        )

    if (
        not isinstance(client_secrets_file, str)
        or not client_secrets_file.strip()
    ):
        raise ValueError("client_secrets_file is required")

    credentials = authorize_youtube(
        client_secrets_file=client_secrets_file,
        authorization_runner=authorization_runner,
    )

    save_youtube_credentials(
        credentials=credentials,
        token_file=token_file,
    )

    return credentials
