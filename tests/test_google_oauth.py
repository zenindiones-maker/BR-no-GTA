from unittest.mock import Mock, patch

import pytest

from app.services.google_oauth import (
    YOUTUBE_UPLOAD_SCOPE,
    create_oauth_flow,
)


def test_youtube_upload_scope_is_correct():
    assert (
        YOUTUBE_UPLOAD_SCOPE
        == "https://www.googleapis.com/auth/youtube.upload"
    )


def test_create_oauth_flow_uses_client_secrets_and_scope():
    fake_flow = Mock()

    with patch(
        "app.services.google_oauth.InstalledAppFlow"
    ) as flow_class:
        flow_class.from_client_secrets_file.return_value = fake_flow

        result = create_oauth_flow(
            client_secrets_file="client_secret.json",
        )

    assert result is fake_flow

    flow_class.from_client_secrets_file.assert_called_once_with(
        "client_secret.json",
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


def test_create_oauth_flow_does_not_execute_authorization():
    fake_flow = Mock()

    with patch(
        "app.services.google_oauth.InstalledAppFlow"
    ) as flow_class:
        flow_class.from_client_secrets_file.return_value = fake_flow

        result = create_oauth_flow(
            client_secrets_file="client_secret.json",
        )

    assert result is fake_flow
    fake_flow.run_local_server.assert_not_called()
    fake_flow.run_console.assert_not_called()
