from app.services.google_youtube_publisher_factory import (
    create_google_youtube_publisher,
)
from app.services.youtube_publication_worker import (
    execute_youtube_publication,
)


def run_google_youtube_publication(
    *,
    publication_id: int,
    token_file: str,
    client_secrets_file: str,
):
    """Executa uma publicação usando o publisher Google real.

    A composição das dependências permanece no Factory.
    O worker permanece agnóstico ao provedor.
    """
    publisher = create_google_youtube_publisher(
        token_file=token_file,
        client_secrets_file=client_secrets_file,
    )

    return execute_youtube_publication(
        publication_id=publication_id,
        publisher=publisher,
    )
