import pytest

from app.services.gta6_confidence_classifier import (
    classify_gta6_confidence,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Rockstar Games officially confirmed the feature.", "confirmed"),
        ("A new official announcement from Rockstar.", "confirmed"),
        ("Insider says GTA 6 may include this feature.", "rumor"),
        ("According to a leak, GTA 6 will have this.", "rumor"),
        ("Fans speculate that Vice City could expand.", "unconfirmed"),
        ("This feature might be coming to GTA 6.", "unconfirmed"),
        ("GTA 6 is reportedly launching on November 19.", "probable"),
    ],
)
def test_classify_gta6_confidence(text, expected):
    assert classify_gta6_confidence(text) == expected


def test_classify_gta6_confidence_is_case_insensitive():
    text = "ROCKSTAR OFFICIALLY CONFIRMED THIS FEATURE"

    assert classify_gta6_confidence(text) == "confirmed"


def test_classify_gta6_confidence_uses_title_and_summary():
    title = "GTA 6 leak reveals new feature"
    summary = "The information was shared by an insider."

    assert classify_gta6_confidence(title, summary) == "rumor"


def test_classify_gta6_confidence_empty_text():
    assert classify_gta6_confidence("") == "unconfirmed"


def test_classify_gta6_confidence_rejects_non_string():
    with pytest.raises(ValueError, match="text must be a string"):
        classify_gta6_confidence(None)
