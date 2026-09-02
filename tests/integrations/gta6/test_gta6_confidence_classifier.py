import pytest

from app.services.gta6_confidence_classifier import (
    classify_gta6_confidence,
)


@pytest.mark.parametrize(
    "text,summary",
    [
        ("Rockstar officially confirmed a new GTA VI feature", ""),
        ("Rockstar announced a new GTA VI feature", ""),
        ("Official announcement about GTA VI", ""),
        ("GTA VI feature", "Rockstar Games confirmed the feature."),
    ],
)
def test_classify_confirmed(text, summary):
    assert classify_gta6_confidence(text, summary) == "confirmed"


@pytest.mark.parametrize(
    "text,summary",
    [
        ("GTA 6 leak reveals new feature", ""),
        ("GTA VI insider shares details", ""),
        ("GTA VI rumor spreads online", ""),
        (
            "GTA VI information",
            "The information was leaked by an insider.",
        ),
    ],
)
def test_classify_rumor(text, summary):
    assert classify_gta6_confidence(text, summary) == "rumor"


@pytest.mark.parametrize(
    "text,summary",
    [
        ("GTA VI release date", "The game is reportedly launching soon."),
        ("GTA VI update", "Sources say the feature is coming."),
        (
            "GTA VI news",
            "According to reports, development is progressing.",
        ),
        ("GTA VI", "The feature is likely to appear in the game."),
    ],
)
def test_classify_probable(text, summary):
    assert classify_gta6_confidence(text, summary) == "probable"


@pytest.mark.parametrize(
    "text,summary",
    [
        ("GTA VI theory", ""),
        ("GTA VI feature", "This could be included in the game."),
        ("GTA VI feature", "It might appear in a future update."),
        ("GTA VI", "The information remains unconfirmed."),
    ],
)
def test_classify_unconfirmed(text, summary):
    assert classify_gta6_confidence(text, summary) == "unconfirmed"


def test_classify_generic_news_as_unconfirmed():
    assert (
        classify_gta6_confidence(
            "GTA VI News",
            "New information about the game.",
        )
        == "unconfirmed"
    )


@pytest.mark.parametrize(
    "text,summary",
    [
        (None, ""),
        ("GTA VI", None),
        (123, ""),
        ("GTA VI", 123),
    ],
)
def test_classify_rejects_invalid_input(text, summary):
    with pytest.raises(ValueError):
        classify_gta6_confidence(text, summary)
