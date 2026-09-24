import pytest

from app.integrations.gta6.rockstar_newswire_adapter import (
    convert_rockstar_article,
    convert_rockstar_articles,
)
from app.integrations.gta6.rockstar_newswire_graph import (
    RockstarNewswireArticle,
)


def make_article() -> RockstarNewswireArticle:
    return RockstarNewswireArticle(
        article_id="666",
        title="GTA VI News",
        url="https://www.rockstargames.com/newswire/gta-vi-news",
        created_at="2026-09-01T12:00:00Z",
        tags=("GTA VI",),
        image_url=None,
    )


def test_convert_rockstar_article():
    source = convert_rockstar_article(make_article())

    assert source.title == "GTA VI News"
    assert source.summary == "GTA VI News"
    assert source.url == (
        "https://www.rockstargames.com/newswire/gta-vi-news"
    )
    assert source.source_name == "Rockstar Newswire"
    assert source.fact_type == "news"
    assert source.confidence == "confirmed"
    assert source.published_at == "2026-09-01T12:00:00Z"


def test_convert_rockstar_articles():
    sources = convert_rockstar_articles(
        [make_article(), make_article()]
    )

    assert len(sources) == 2
    assert all(
        source.source_name == "Rockstar Newswire"
        for source in sources
    )


def test_convert_rejects_invalid_article():
    with pytest.raises(ValueError):
        convert_rockstar_article("invalid")


def test_convert_rejects_invalid_list():
    with pytest.raises(ValueError):
        convert_rockstar_articles("invalid")

def test_parse_current_newswire_listing_falls_back_to_gta6_article_links():
    html = """
    <html><body>
      <a href="/newswire/article/abc123/pre-order-the-goodtime-state">
        Pre-Order The Goodtime State – Vice City Collection Now
      </a>
      <a href="/newswire/article/other/gta-online-event">
        GTA Online Weekly Event
      </a>
    </body></html>
    """

    result = parse_rockstar_newswire_html(html)

    assert len(result) == 1
    assert result[0].title.startswith("Pre-Order The Goodtime State")
    assert result[0].url == (
        "https://www.rockstargames.com/newswire/article/abc123/"
        "pre-order-the-goodtime-state"
    )
