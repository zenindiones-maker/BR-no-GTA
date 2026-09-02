from pathlib import Path

import app.services.google_youtube_configuration as configuration


def test_get_youtube_token_file_uses_canonical_settings_directory(
    monkeypatch,
):
    monkeypatch.setattr(
        configuration.settings,
        "YOUTUBE_TOKENS_DIR",
        Path("/tmp/youtube/tokens"),
    )

    result = configuration.get_youtube_token_file()

    assert result == "/tmp/youtube/tokens/youtube_token.json"


def test_get_youtube_client_secrets_file_uses_canonical_settings_directory(
    monkeypatch,
):
    monkeypatch.setattr(
        configuration.settings,
        "YOUTUBE_CREDENTIALS_DIR",
        Path("/tmp/youtube/credentials"),
    )

    result = configuration.get_youtube_client_secrets_file()

    assert result == (
        "/tmp/youtube/credentials/client_secret.json"
    )
