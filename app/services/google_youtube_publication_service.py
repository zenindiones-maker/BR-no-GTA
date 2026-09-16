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
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    validate_harness_authorization,
)
from app.services.youtube_publication_orchestration import (
    make_youtube_publication_public,
    reconcile_youtube_publication_visibility,
    upload_youtube_publication,
)

PRIVATE_UPLOAD_CAPABILITY_ID = "youtube.upload-private"
PUBLICATION_CAPABILITY_ID = "youtube.publish-public"


def _create_google_publisher(
    *,
    token_file: str | None = None,
    client_secrets_file: str | None = None,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> Any:
    resolved_token_file = token_file if token_file is not None else get_youtube_token_file()
    resolved_client_secrets_file = (
        client_secrets_file
        if client_secrets_file is not None
        else get_youtube_client_secrets_file()
    )
    if not isinstance(resolved_token_file, str) or not resolved_token_file.strip():
        raise ValueError("token_file is required")
    if not isinstance(resolved_client_secrets_file, str) or not resolved_client_secrets_file.strip():
        raise ValueError("client_secrets_file is required")
    return create_google_youtube_publisher(
        token_file=resolved_token_file,
        client_secrets_file=resolved_client_secrets_file,
        authorization_runner=authorization_runner,
        request=request,
    )


def _require_pending_publication(publication_id: int) -> dict[str, Any]:
    if not isinstance(publication_id, int) or isinstance(publication_id, bool) or publication_id <= 0:
        raise ValueError("publication_id must be a positive integer")
    publication = get_youtube_publication(publication_id)
    if publication is None:
        raise ValueError(f"YouTube publication not found: {publication_id}")
    if publication.get("status") != "pending":
        raise ValueError(f"YouTube publication is not pending: {publication_id}")
    return publication


def upload_youtube_publication_with_google(
    *,
    publication_id: int,
    authorization: object | None = None,
    authorization_subject: str = "action:YOUTUBE",
    token_file: str | None = None,
    client_secrets_file: str | None = None,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """Upload one persisted Publication as private under Harness authority.

    ``authorization_subject`` defaults to the legacy generic YOUTUBE boundary.
    Exact target callers use ``youtube:publication:{id}``.  The authorization is
    consumed immediately before the external upload side effect.
    """
    publication = _require_pending_publication(publication_id)
    harness_authorization = validate_harness_authorization(
        authorization or {},
        expected_action="YOUTUBE",
        expected_subject=authorization_subject,
    )
    publisher = _create_google_publisher(
        token_file=token_file,
        client_secrets_file=client_secrets_file,
        authorization_runner=authorization_runner,
        request=request,
    )
    consume_harness_authorization(harness_authorization)
    return upload_youtube_publication(
        publication_id=publication["id"],
        publisher=publisher,
    )


def process_youtube_publication(
    publication_id: int,
    execution_context: dict[str, Any] | None = None,
    *,
    token_file: str | None = None,
    client_secrets_file: str | None = None,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """Upload the exact Publication selected by the Harness.

    No global queue claim occurs here.  The persisted authorization must bind
    the exact publication and the registered private-upload capability.
    """
    publication = _require_pending_publication(publication_id)
    context = execution_context or {}
    execution_id = context.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id:
        raise PermissionError("Harness execution_id is required for targeted YOUTUBE upload")
    authorization = validate_harness_authorization(
        context,
        expected_action="YOUTUBE",
        expected_subject=f"youtube:publication:{publication_id}",
        expected_execution_id=execution_id,
    )
    lineage = authorization.lineage or {}
    if lineage.get("publication_id") != publication_id:
        raise PermissionError("targeted YouTube authorization publication mismatch")
    if lineage.get("capability_id") != PRIVATE_UPLOAD_CAPABILITY_ID:
        raise PermissionError("targeted YouTube authorization capability mismatch")
    return upload_youtube_publication_with_google(
        publication_id=publication["id"],
        authorization=authorization,
        authorization_subject=f"youtube:publication:{publication_id}",
        token_file=token_file,
        client_secrets_file=client_secrets_file,
        authorization_runner=authorization_runner,
        request=request,
    )


def make_youtube_publication_public_with_google(
    *,
    publication_id: int,
    authorization: object | None = None,
    token_file: str | None = None,
    client_secrets_file: str | None = None,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """Make one already-uploaded Publication public under Harness authority."""
    if not isinstance(publication_id, int) or isinstance(publication_id, bool) or publication_id <= 0:
        raise ValueError("publication_id must be a positive integer")
    harness_authorization = validate_harness_authorization(
        authorization or {},
        expected_action="PUBLICATION",
        expected_subject=f"youtube:publication:{publication_id}",
    )
    publication = get_youtube_publication(publication_id)
    if publication is None:
        raise ValueError(f"YouTube publication not found: {publication_id}")
    if publication["status"] != "uploaded":
        raise ValueError(f"YouTube publication is not uploaded: {publication_id}")
    publisher = _create_google_publisher(
        token_file=token_file,
        client_secrets_file=client_secrets_file,
        authorization_runner=authorization_runner,
        request=request,
    )
    return make_youtube_publication_public(
        publication_id=publication_id,
        publisher=publisher,
        authorization=harness_authorization,
    )


def reconcile_youtube_publication_visibility_with_google(
    *,
    publication_id: int,
    token_file: str | None = None,
    client_secrets_file: str | None = None,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """Read remote visibility and reconcile an uncertain public transition."""
    if not isinstance(publication_id, int) or isinstance(publication_id, bool) or publication_id <= 0:
        raise ValueError("publication_id must be a positive integer")
    publication = get_youtube_publication(publication_id)
    if publication is None:
        raise ValueError(f"YouTube publication not found: {publication_id}")
    publisher = _create_google_publisher(
        token_file=token_file,
        client_secrets_file=client_secrets_file,
        authorization_runner=authorization_runner,
        request=request,
    )
    return reconcile_youtube_publication_visibility(
        publication_id=publication_id,
        publisher=publisher,
    )


def process_next_youtube_publication(
    execution_context: dict[str, Any] | None = None,
    *,
    token_file: str | None = None,
    client_secrets_file: str | None = None,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> dict[str, Any] | None:
    """Legacy generic queue upload boundary; exact-target callers must not use it."""
    context = execution_context or {}
    execution_id = context.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id:
        raise PermissionError("Harness execution_id is required for YOUTUBE")
    harness_authorization = validate_harness_authorization(
        context,
        expected_action="YOUTUBE",
        expected_subject="action:YOUTUBE",
        expected_execution_id=execution_id,
    )
    publication = get_next_pending_youtube_publication()
    if publication is None:
        return None
    publication_id = publication.get("id")
    if not isinstance(publication_id, int) or publication_id <= 0:
        raise ValueError("pending YouTube publication must have a valid id")
    return upload_youtube_publication_with_google(
        publication_id=publication_id,
        authorization=harness_authorization,
        token_file=token_file,
        client_secrets_file=client_secrets_file,
        authorization_runner=authorization_runner,
        request=request,
    )
