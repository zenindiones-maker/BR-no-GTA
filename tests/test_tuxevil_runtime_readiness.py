from pathlib import Path

from scripts.tuxevil_runtime_readiness import config_shape, redact_text


def test_redact_text_removes_credentials_and_email():
    raw = (
        "Authorization: Bearer secret-token\n"
        "refreshToken=refresh-secret\n"
        "api_key=api-secret\n"
        "rk-abcdef123456\n"
        "person@example.com\n"
    )
    redacted = redact_text(raw)
    assert "secret-token" not in redacted
    assert "refresh-secret" not in redacted
    assert "api-secret" not in redacted
    assert "rk-abcdef123456" not in redacted
    assert "person@example.com" not in redacted
    assert "[REDACTED" in redacted


def test_config_shape_counts_antigravity_without_reading_identity_fields(
    tmp_path: Path,
):
    (tmp_path / "accounts.json").write_text(
        """{
  "accounts": [
    {
      "email": "should-never-be-emitted@example.com",
      "refreshToken": "should-never-be-emitted",
      "provider": "google-antigravity"
    }
  ]
}
""",
        encoding="utf-8",
    )
    count, providers = config_shape(tmp_path)
    assert count == 1
    assert providers == {"google-antigravity"}
