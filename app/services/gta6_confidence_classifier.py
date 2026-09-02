CONFIRMED_MARKERS = (
    "officially confirmed",
    "official confirmation",
    "official announcement",
    "rockstar confirmed",
    "rockstar games confirmed",
    "confirmed by rockstar",
)

RUMOR_MARKERS = (
    "leak",
    "leaked",
    "insider",
    "rumor",
    "rumour",
)

PROBABLE_MARKERS = (
    "expected",
    "likely",
    "reportedly",
    "report says",
    "according to reports",
)

UNCONFIRMED_MARKERS = (
    "speculate",
    "speculation",
    "could",
    "might",
    "may",
    "theory",
)


def classify_gta6_confidence(
    text: str,
    summary: str = "",
) -> str:
    if not isinstance(text, str) or not isinstance(summary, str):
        raise ValueError("text must be a string")

    combined = f"{text} {summary}".strip().lower()

    if any(marker in combined for marker in CONFIRMED_MARKERS):
        return "confirmed"

    if any(marker in combined for marker in RUMOR_MARKERS):
        return "rumor"

    if any(marker in combined for marker in PROBABLE_MARKERS):
        return "probable"

    if any(marker in combined for marker in UNCONFIRMED_MARKERS):
        return "unconfirmed"

    return "unconfirmed"
