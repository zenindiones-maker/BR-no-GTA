from typing import Any

from googleapiclient.discovery import build


def create_youtube_service(
    credentials: Any,
) -> Any:
    """
    Cria um cliente autenticado da API do YouTube.

    Responsabilidades:
    - receber Credentials já autenticadas;
    - construir o cliente da API YouTube v3.

    Não é responsabilidade desta função:
    - executar OAuth;
    - carregar tokens;
    - salvar tokens;
    - acessar SQLite;
    - publicar vídeos;
    - alterar estado de publicação.
    """

    if credentials is None:
        raise ValueError("credentials are required")

    return build(
        "youtube",
        "v3",
        credentials=credentials,
    )
