from pathlib import Path

from app.settings import settings


def get_youtube_token_file() -> str:
    """
    Retorna o caminho canônico do token OAuth do YouTube.

    A configuração de infraestrutura permanece centralizada
    em app.settings.
    """

    token_file = (
        Path(settings.YOUTUBE_TOKENS_DIR)
        / "youtube_token.json"
    )

    return str(token_file)


def get_youtube_client_secrets_file() -> str:
    """
    Retorna o caminho canônico das credenciais OAuth
    utilizadas para autorizar o YouTube.

    O arquivo de client secrets pertence à configuração
    de infraestrutura e não ao Publisher.
    """

    client_secrets_file = (
        Path(settings.YOUTUBE_CREDENTIALS_DIR)
        / "client_secret.json"
    )

    return str(client_secrets_file)
