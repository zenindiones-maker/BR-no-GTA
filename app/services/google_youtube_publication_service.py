from typing import Any, Callable

from app.database.youtube_repository import (
    get_next_pending_youtube_publication,
    get_youtube_publication,
)
from app.services.google_youtube_configuration import (
    get_youtube_client_secrets_file,
    get_youtube_token_file,
)
from app.services.google_youtube_publisher_factory import (
    create_google_youtube_publisher,
)
from app.services.youtube_publication_orchestration import (
    make_youtube_publication_public,
    upload_youtube_publication,
)


def _create_google_publisher(
    *,
    token_file: str | None = None,
    client_secrets_file: str | None = None,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> Any:
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

    return create_google_youtube_publisher(
        token_file=resolved_token_file,
        client_secrets_file=resolved_client_secrets_file,
        authorization_runner=authorization_runner,
        request=request,
    )


def upload_youtube_publication_with_google(
    *,
    publication_id: int,
    token_file: str | None = None,
    client_secrets_file: str | None = None,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Faz upload de uma YouTube Publication usando o Publisher real do Google.

    O vídeo é enviado ao YouTube como privado.

    Esta função não torna o vídeo público.
    """

    if not isinstance(publication_id, int) or publication_id <= 0:
        raise ValueError(
            "publication_id must be a positive integer"
        )

    publisher = _create_google_publisher(
        token_file=token_file,
        client_secrets_file=client_secrets_file,
        authorization_runner=authorization_runner,
        request=request,
    )

    return upload_youtube_publication(
        publication_id=publication_id,
        publisher=publisher,
    )


def make_youtube_publication_public_with_google(
    *,
    publication_id: int,
    token_file: str | None = None,
    client_secrets_file: str | None = None,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Torna público um vídeo previamente enviado ao YouTube.

    Esta operação exige que a publicação esteja em estado ``uploaded``.
    """

    if not isinstance(publication_id, int) or publication_id <= 0:
        raise ValueError(
            "publication_id must be a positive integer"
        )

    publication = get_youtube_publication(publication_id)

    if publication is None:
        raise ValueError(
            f"YouTube publication not found: {publication_id}"
        )

    if publication["status"] != "uploaded":
        raise ValueError(
            "YouTube publication is not uploaded: "
            f"{publication_id}"
        )

    publisher = _create_google_publisher(
        token_file=token_file,
        client_secrets_file=client_secrets_file,
        authorization_runner=authorization_runner,
        request=request,
    )

    return make_youtube_publication_public(
        publication_id=publication_id,
        publisher=publisher,
    )


def process_next_youtube_publication(
    *,
    token_file: str | None = None,
    client_secrets_file: str | None = None,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> dict[str, Any] | None:
    """
    Processa a próxima publicação YouTube pendente.

    Esta operação executa somente o upload privado.

    Retorna None quando não há publicação pendente.
    """

    publication = get_next_pending_youtube_publication()

    if publication is None:
        return None

    publication_id = publication.get("id")

    if not isinstance(publication_id, int) or publication_id <= 0:
        raise ValueError(
            "pending YouTube publication must have a valid id"
        )

    return upload_youtube_publication_with_google(
        publication_id=publication_id,
        token_file=token_file,
        client_secrets_file=client_secrets_file,
        authorization_runner=authorization_runner,
        request=request,
    )
