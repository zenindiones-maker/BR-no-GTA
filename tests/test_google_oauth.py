from unittest.mock import Mock, patch

import pytest

from app.services.google_oauth import (
    YOUTUBE_UPLOAD_SCOPE,
    authorize_youtube,
    create_oauth_flow,
    get_youtube_credentials,
    load_youtube_credentials,
    save_youtube_credentials,
)


def test_youtube_upload_scope_is_correct():
    assert (
        YOUTUBE_UPLOAD_SCOPE
        == "https://www.googleapis.com/auth/youtube.upload"
    )


def test_create_oauth_flow_uses_client_secrets_and_scope(tmp_path):
    fake_flow = Mock()
    client_secrets_file = tmp_path / "client_secret.json"
    client_secrets_file.write_text("fake client secrets")

    with patch(
        "app.services.google_oauth.InstalledAppFlow"
    ) as flow_class:
        flow_class.from_client_secrets_file.return_value = fake_flow

        result = create_oauth_flow(
            client_secrets_file=str(client_secrets_file),
        )

    assert result is fake_flow

    flow_class.from_client_secrets_file.assert_called_once_with(
        str(client_secrets_file),
        scopes=[YOUTUBE_UPLOAD_SCOPE],
    )


def test_create_oauth_flow_rejects_missing_client_secrets():
    with pytest.raises(
        ValueError,
        match="client_secrets_file is required",
    ):
        create_oauth_flow(
            client_secrets_file="",
        )


def test_create_oauth_flow_does_not_execute_authorization(tmp_path):
    fake_flow = Mock()
    client_secrets_file = tmp_path / "client_secret.json"
    client_secrets_file.write_text("fake client secrets")

    with patch(
        "app.services.google_oauth.InstalledAppFlow"
    ) as flow_class:
        flow_class.from_client_secrets_file.return_value = fake_flow

        result = create_oauth_flow(
            client_secrets_file=str(client_secrets_file),
        )

    assert result is fake_flow
    fake_flow.run_local_server.assert_not_called()
    fake_flow.run_console.assert_not_called()


def test_create_oauth_flow_rejects_nonexistent_file(tmp_path):
    missing_file = tmp_path / "missing.json"

    with pytest.raises(
        ValueError,
        match="client secrets file not found",
    ):
        create_oauth_flow(
            client_secrets_file=str(missing_file),
        )


def test_authorize_youtube_uses_injected_runner(tmp_path):
    client_secrets = tmp_path / "client_secret.json"
    client_secrets.write_text("{}")

    fake_flow = Mock()
    fake_credentials = Mock()

    def fake_runner(flow):
        assert flow is fake_flow
        return fake_credentials

    with patch(
        "app.services.google_oauth.InstalledAppFlow"
    ) as flow_class:
        flow_class.from_client_secrets_file.return_value = fake_flow

        result = authorize_youtube(
            client_secrets_file=str(client_secrets),
            authorization_runner=fake_runner,
        )

    assert result is fake_credentials
    fake_flow.run_local_server.assert_not_called()


def test_authorize_youtube_uses_default_authorization_flow(tmp_path):
    client_secrets = tmp_path / "client_secret.json"
    client_secrets.write_text("{}")

    fake_flow = Mock()
    fake_credentials = Mock()

    fake_flow.run_local_server.return_value = fake_credentials

    with patch(
        "app.services.google_oauth.InstalledAppFlow"
    ) as flow_class:
        flow_class.from_client_secrets_file.return_value = fake_flow

        result = authorize_youtube(
            client_secrets_file=str(client_secrets),
        )

    assert result is fake_credentials

    fake_flow.run_local_server.assert_called_once_with(
        port=0,
        access_type="offline",
        prompt="consent",
    )


def test_authorize_youtube_rejects_missing_credentials(tmp_path):
    client_secrets = tmp_path / "client_secret.json"
    client_secrets.write_text("{}")

    fake_flow = Mock()
    fake_flow.run_local_server.return_value = None

    with patch(
        "app.services.google_oauth.InstalledAppFlow"
    ) as flow_class:
        flow_class.from_client_secrets_file.return_value = fake_flow

        with pytest.raises(
            RuntimeError,
            match="OAuth authorization did not return credentials",
        ):
            authorize_youtube(
                client_secrets_file=str(client_secrets),
            )


def test_save_youtube_credentials_writes_json(tmp_path):
    token_file = tmp_path / "oauth" / "token.json"

    credentials = Mock()
    credentials.to_json.return_value = '{"token": "access-token"}'

    save_youtube_credentials(
        credentials=credentials,
        token_file=str(token_file),
    )

    assert token_file.is_file()
    assert token_file.read_text(encoding="utf-8") == (
        '{"token": "access-token"}'
    )

    credentials.to_json.assert_called_once_with()


def test_save_youtube_credentials_creates_parent_directory(
    tmp_path,
):
    token_file = tmp_path / "nested" / "oauth" / "token.json"

    credentials = Mock()
    credentials.to_json.return_value = "{}"

    save_youtube_credentials(
        credentials=credentials,
        token_file=str(token_file),
    )

    assert token_file.is_file()
    assert token_file.read_text(encoding="utf-8") == "{}"


def test_save_youtube_credentials_rejects_missing_credentials(
    tmp_path,
):
    token_file = tmp_path / "token.json"

    with pytest.raises(
        ValueError,
        match="credentials are required",
    ):
        save_youtube_credentials(
            credentials=None,
            token_file=str(token_file),
        )


def test_save_youtube_credentials_rejects_missing_token_file():
    credentials = Mock()

    with pytest.raises(
        ValueError,
        match="token_file is required",
    ):
        save_youtube_credentials(
            credentials=credentials,
            token_file="",
        )


def test_load_youtube_credentials_returns_valid_credentials(
    tmp_path,
):
    token_file = tmp_path / "token.json"
    token_file.write_text("{}")

    credentials = Mock()
    credentials.valid = True

    with patch(
        "app.services.google_oauth.Credentials"
    ) as credentials_class:
        credentials_class.from_authorized_user_file.return_value = (
            credentials
        )

        result = load_youtube_credentials(
            token_file=str(token_file),
        )

    assert result is credentials

    credentials_class.from_authorized_user_file.assert_called_once_with(
        str(token_file),
        scopes=[YOUTUBE_UPLOAD_SCOPE],
    )

    credentials.refresh.assert_not_called()


def test_load_youtube_credentials_rejects_missing_token_file(
    tmp_path,
):
    token_file = tmp_path / "missing.json"

    with pytest.raises(
        ValueError,
        match="token file not found",
    ):
        load_youtube_credentials(
            token_file=str(token_file),
        )


def test_load_youtube_credentials_refreshes_expired_credentials(
    tmp_path,
):
    token_file = tmp_path / "token.json"
    token_file.write_text("{}")

    credentials = Mock()
    credentials.valid = False
    credentials.expired = True
    credentials.refresh_token = "refresh-token"
    credentials.to_json.return_value = (
        '{"token": "refreshed-token"}'
    )

    request = Mock()

    with patch(
        "app.services.google_oauth.Credentials"
    ) as credentials_class:
        credentials_class.from_authorized_user_file.return_value = (
            credentials
        )

        with patch(
            "app.services.google_oauth.Request"
        ) as request_class:
            result = load_youtube_credentials(
                token_file=str(token_file),
                request=request,
            )

    assert result is credentials

    credentials.refresh.assert_called_once_with(request)

    request_class.assert_not_called()

    assert token_file.read_text(encoding="utf-8") == (
        '{"token": "refreshed-token"}'
    )


def test_load_youtube_credentials_creates_default_request_when_refreshing(
    tmp_path,
):
    token_file = tmp_path / "token.json"
    token_file.write_text("{}")

    credentials = Mock()
    credentials.valid = False
    credentials.expired = True
    credentials.refresh_token = "refresh-token"
    credentials.to_json.return_value = "{}"

    generated_request = Mock()

    with patch(
        "app.services.google_oauth.Credentials"
    ) as credentials_class:
        credentials_class.from_authorized_user_file.return_value = (
            credentials
        )

        with patch(
            "app.services.google_oauth.Request",
            return_value=generated_request,
        ) as request_class:
            result = load_youtube_credentials(
                token_file=str(token_file),
            )

    assert result is credentials

    request_class.assert_called_once_with()
    credentials.refresh.assert_called_once_with(
        generated_request
    )


def test_load_youtube_credentials_rejects_unrefreshable_credentials(
    tmp_path,
):
    token_file = tmp_path / "token.json"
    token_file.write_text("{}")

    credentials = Mock()
    credentials.valid = False
    credentials.expired = True
    credentials.refresh_token = None

    with patch(
        "app.services.google_oauth.Credentials"
    ) as credentials_class:
        credentials_class.from_authorized_user_file.return_value = (
            credentials
        )

        with pytest.raises(
            RuntimeError,
            match=(
                "YouTube OAuth credentials are invalid "
                "or cannot be refreshed"
            ),
        ):
            load_youtube_credentials(
                token_file=str(token_file),
            )

    credentials.refresh.assert_not_called()


def test_load_youtube_credentials_rejects_invalid_nonexpired_credentials(
    tmp_path,
):
    token_file = tmp_path / "token.json"
    token_file.write_text("{}")

    credentials = Mock()
    credentials.valid = False
    credentials.expired = False
    credentials.refresh_token = None

    with patch(
        "app.services.google_oauth.Credentials"
    ) as credentials_class:
        credentials_class.from_authorized_user_file.return_value = (
            credentials
        )

        with pytest.raises(
            RuntimeError,
            match=(
                "YouTube OAuth credentials are invalid "
                "or cannot be refreshed"
            ),
        ):
            load_youtube_credentials(
                token_file=str(token_file),
            )

    credentials.refresh.assert_not_called()


def test_get_youtube_credentials_loads_existing_token(
    tmp_path,
):
    token_file = tmp_path / "token.json"
    token_file.write_text("{}")

    credentials = Mock()

    with patch(
        "app.services.google_oauth.load_youtube_credentials"
    ) as load_credentials:
        load_credentials.return_value = credentials

        result = get_youtube_credentials(
            token_file=str(token_file),
            client_secrets_file="",
        )

    assert result is credentials

    load_credentials.assert_called_once_with(
        token_file=str(token_file),
        request=None,
    )


def test_get_youtube_credentials_authorizes_when_token_is_missing(
    tmp_path,
):
    token_file = tmp_path / "token.json"
    client_secrets_file = tmp_path / "client_secret.json"

    credentials = Mock()

    client_secrets_file.write_text("{}")

    with patch(
        "app.services.google_oauth.authorize_youtube"
    ) as authorize:
        with patch(
            "app.services.google_oauth.save_youtube_credentials"
        ) as save_credentials:
            authorize.return_value = credentials

            result = get_youtube_credentials(
                token_file=str(token_file),
                client_secrets_file=str(client_secrets_file),
            )

    assert result is credentials

    authorize.assert_called_once_with(
        client_secrets_file=str(client_secrets_file),
        authorization_runner=None,
    )

    save_credentials.assert_called_once_with(
        credentials=credentials,
        token_file=str(token_file),
    )


def test_get_youtube_credentials_passes_injected_authorization_runner(
    tmp_path,
):
    token_file = tmp_path / "token.json"
    client_secrets_file = tmp_path / "client_secret.json"

    client_secrets_file.write_text("{}")

    credentials = Mock()
    authorization_runner = Mock()

    with patch(
        "app.services.google_oauth.authorize_youtube"
    ) as authorize:
        with patch(
            "app.services.google_oauth.save_youtube_credentials"
        ) as save_credentials:
            authorize.return_value = credentials

            result = get_youtube_credentials(
                token_file=str(token_file),
                client_secrets_file=str(client_secrets_file),
                authorization_runner=authorization_runner,
            )

    assert result is credentials

    authorize.assert_called_once_with(
        client_secrets_file=str(client_secrets_file),
        authorization_runner=authorization_runner,
    )

    save_credentials.assert_called_once_with(
        credentials=credentials,
        token_file=str(token_file),
    )


def test_get_youtube_credentials_rejects_missing_token_file_argument():
    try:
        get_youtube_credentials(
            token_file="",
            client_secrets_file="client_secret.json",
        )
    except ValueError as exc:
        assert str(exc) == "token_file is required"
    else:
        raise AssertionError(
            "Expected ValueError when token_file is missing"
        )


def test_get_youtube_credentials_rejects_missing_client_secrets_argument(
    tmp_path,
):
    token_file = tmp_path / "token.json"

    try:
        get_youtube_credentials(
            token_file=str(token_file),
            client_secrets_file="",
        )
    except ValueError as exc:
        assert str(exc) == "client_secrets_file is required"
    else:
        raise AssertionError(
            "Expected ValueError when client_secrets_file is missing"
        )
