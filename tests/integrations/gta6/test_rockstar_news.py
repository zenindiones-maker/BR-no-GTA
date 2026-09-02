import pytest

from app.integrations.gta6.rockstar_news import (
    fetch_rockstar_newswire,
    parse_rockstar_newswire_html,
)


def test_parse_rockstar_newswire_gta6_article():
    html = """
    <html>
        <body>
            <a href="/newswire/article/grand-theft-auto-vi-trailer">
                Grand Theft Auto VI Trailer
            </a>
        </body>
    </html>
    """

    items = parse_rockstar_newswire_html(html)

    assert len(items) == 1

    item = items[0]

    assert item.title == "Grand Theft Auto VI Trailer"
    assert item.source_name == "Rockstar Newswire"
    assert item.fact_type == "news"
    assert item.confidence == "confirmed"
    assert item.url == (
        "https://www.rockstargames.com"
        "/newswire/article/grand-theft-auto-vi-trailer"
    )


def test_parse_rockstar_newswire_ignores_non_gta6_articles():
    html = """
    <html>
        <body>
            <a href="/newswire/article/red-dead-online">
                Red Dead Online
            </a>

            <a href="/newswire/article/grand-theft-auto-vi-news">
                GTA VI News
            </a>
        </body>
    </html>
    """

    items = parse_rockstar_newswire_html(html)

    assert len(items) == 1
    assert items[0].title == "GTA VI News"


def test_parse_rockstar_newswire_supports_absolute_urls():
    html = """
    <a href="https://www.rockstargames.com/newswire/article/grand-theft-auto-vi">
        GTA VI
    </a>
    """

    items = parse_rockstar_newswire_html(html)

    assert len(items) == 1
    assert items[0].url.startswith(
        "https://www.rockstargames.com/"
    )


def test_parse_rockstar_newswire_returns_empty_when_no_gta6():
    html = """
    <a href="/newswire/article/gtav">
        GTA V
    </a>
    """

    assert parse_rockstar_newswire_html(html) == []


def test_fetch_rockstar_newswire_wraps_network_failure(monkeypatch):
    def fake_urlopen(*args, **kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(
        "app.integrations.gta6.rockstar_news.urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        RuntimeError,
        match="failed to fetch Rockstar Newswire",
    ):
        fetch_rockstar_newswire()
