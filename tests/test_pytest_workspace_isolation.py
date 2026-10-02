from pathlib import Path


def test_pytest_tmp_path_retention_is_bounded_for_long_lived_sprite():
    config = Path("pytest.ini").read_text(encoding="utf-8")
    assert "tmp_path_retention_count = 1" in config
