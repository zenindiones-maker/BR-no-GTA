from pathlib import Path
from typing import Any, Callable, Iterable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
YOUTUBE_ANALYTICS_READ_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"


def _resolved_scopes(scopes: Iterable[str] | None) -> list[str]:
    requested = list(scopes or ())
    return list(dict.fromkeys([*YOUTUBE_SCOPES, *requested]))


def create_oauth_flow(*, client_secrets_file: str, scopes: Iterable[str] | None = None) -> Any:
    if not isinstance(client_secrets_file, str) or not client_secrets_file.strip():
        raise ValueError("client_secrets_file is required")
    path = Path(client_secrets_file)
    if not path.is_file():
        raise ValueError(f"client secrets file not found: {client_secrets_file}")
    return InstalledAppFlow.from_client_secrets_file(str(path), scopes=_resolved_scopes(scopes))


def authorize_youtube(*, client_secrets_file: str,
                      authorization_runner: Callable[[Any], Any] | None = None,
                      scopes: Iterable[str] | None = None) -> Any:
    flow = create_oauth_flow(client_secrets_file=client_secrets_file, scopes=scopes)
    credentials = authorization_runner(flow) if authorization_runner is not None else flow.run_local_server(
        port=0, access_type="offline", prompt="consent", open_browser=False
    )
    if credentials is None:
        raise RuntimeError("OAuth authorization did not return credentials")
    return credentials


def save_youtube_credentials(*, credentials: Any, token_file: str) -> None:
    if credentials is None:
        raise ValueError("credentials are required")
    if not isinstance(token_file, str) or not token_file.strip():
        raise ValueError("token_file is required")
    path = Path(token_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(credentials.to_json(), encoding="utf-8")


def load_youtube_credentials(*, token_file: str, request: Any | None = None,
                             scopes: Iterable[str] | None = None) -> Credentials:
    if not isinstance(token_file, str) or not token_file.strip():
        raise ValueError("token_file is required")
    path = Path(token_file)
    if not path.is_file():
        raise ValueError(f"token file not found: {token_file}")
    required_scopes = _resolved_scopes(scopes)
    credentials = Credentials.from_authorized_user_file(str(path), scopes=required_scopes)
    if scopes and not credentials.has_scopes(list(scopes)):
        missing = ", ".join(scope for scope in scopes if not credentials.has_scopes([scope]))
        raise PermissionError(f"Persisted YouTube OAuth credentials are missing required scope(s): {missing}")
    if credentials.valid:
        return credentials
    if credentials.expired and credentials.refresh_token:
        refresh_request = request if request is not None else Request()
        credentials.refresh(refresh_request)
        if scopes and not credentials.has_scopes(list(scopes)):
            missing = ", ".join(scope for scope in scopes if not credentials.has_scopes([scope]))
            raise PermissionError(f"Refreshed YouTube OAuth credentials are missing required scope(s): {missing}")
        save_youtube_credentials(credentials=credentials, token_file=str(path))
        return credentials
    raise RuntimeError("YouTube OAuth credentials are invalid or cannot be refreshed")


def get_youtube_credentials(*, token_file: str, client_secrets_file: str,
                            authorization_runner: Callable[[Any], Any] | None = None,
                            request: Any | None = None,
                            scopes: Iterable[str] | None = None) -> Any:
    if not isinstance(token_file, str) or not token_file.strip():
        raise ValueError("token_file is required")
    token_path = Path(token_file)
    if token_path.is_file():
        if scopes is None:
            return load_youtube_credentials(token_file=token_file, request=request)
        return load_youtube_credentials(token_file=token_file, request=request, scopes=scopes)
    if not isinstance(client_secrets_file, str) or not client_secrets_file.strip():
        raise ValueError("client_secrets_file is required")
    if scopes is None:
        credentials = authorize_youtube(
            client_secrets_file=client_secrets_file,
            authorization_runner=authorization_runner,
        )
    else:
        credentials = authorize_youtube(
            client_secrets_file=client_secrets_file,
            authorization_runner=authorization_runner,
            scopes=scopes,
        )
    if scopes and not credentials.has_scopes(list(scopes)):
        missing = ", ".join(scope for scope in scopes if not credentials.has_scopes([scope]))
        raise PermissionError(f"YouTube OAuth authorization did not grant required scope(s): {missing}")
    save_youtube_credentials(credentials=credentials, token_file=token_file)
    return credentials
