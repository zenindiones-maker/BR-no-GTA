from unittest.mock import Mock, patch

import pytest

from app.services.google_oauth import (
    YOUTUBE_UPLOAD_SCOPE,
    authorize_youtube,
    create_oauth_flow,
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


def test_create_oauth_flow_rejects_nonexistent_file(
    tmp_path: Path,
):
    missing_file = tmp_path / "missing.json"

    with pytest.raises(
        ValueError,
        match="client secrets file not found",
    ):
        create_oauth_flow(
            client_secrets_file=str(missing_file),
        )


def test_authorize_youtube_uses_injected_runner(
    tmp_path: Path,
):
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


def test_authorize_youtube_uses_default_authorization_flow(
    tmp_path: Path,
):
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


def test_authorize_youtube_rejects_missing_credentials(
    tmp_path: Path,
):
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
