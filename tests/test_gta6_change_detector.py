from app.services.gta6_change_detector import (
    detect_content_change,
    hash_monitored_content,
    normalize_monitored_content,
)


def test_normalize_removes_script_and_style():
    content = """
    <html>
        <style>.dynamic { color: red; }</style>
        GTA VI
        <script>tracking()</script>
        Release date: 2026
    </html>
    """

    result = normalize_monitored_content(content)

    assert "tracking()" not in result
    assert "dynamic" not in result
    assert "GTA VI" in result
    assert "Release date: 2026" in result


def test_hash_is_stable_for_same_content():
    content = "GTA VI release date"

    assert hash_monitored_content(content) == (
        hash_monitored_content(content)
    )


def test_first_observation_is_change():
    result = detect_content_change(
        "GTA VI release date",
        None,
    )

    assert result.changed is True
    assert result.previous_hash is None
    assert result.current_hash


def test_same_content_is_not_change():
    content = "GTA VI release date"

    previous_hash = hash_monitored_content(content)

    result = detect_content_change(
        content,
        previous_hash,
    )

    assert result.changed is False
    assert result.previous_hash == previous_hash
    assert result.current_hash == previous_hash


def test_changed_content_is_detected():
    previous_hash = hash_monitored_content(
        "GTA VI release date: 2026"
    )

    result = detect_content_change(
        "GTA VI release date: 2027",
        previous_hash,
    )

    assert result.changed is True
    assert result.previous_hash != result.current_hash


def test_script_only_change_is_ignored():
    previous_hash = hash_monitored_content(
        """
        <html>
            GTA VI
            <script>version=1</script>
        </html>
        """
    )

    result = detect_content_change(
        """
        <html>
            GTA VI
            <script>version=2</script>
        </html>
        """,
        previous_hash,
    )

    assert result.changed is False


def test_invalid_content_is_rejected():
    try:
        normalize_monitored_content(None)
    except ValueError as exc:
        assert str(exc) == "content must be a string"
    else:
        raise AssertionError("ValueError was expected")


def test_invalid_previous_hash_is_rejected():
    try:
        detect_content_change("GTA VI", "")
    except ValueError as exc:
        assert str(exc) == (
            "previous_hash must be a non-empty string or None"
        )
    else:
        raise AssertionError("ValueError was expected")
