from app.integrations.gta6.rockstar_newswire_adapter import (
    parse_rockstar_newswire_html,
)


def test_parse_rockstar_newswire_html_extracts_article():
    html = """
    <html>
      <script type="application/ld+json">
      {
        "@type": "NewsArticle",
        "headline": "GTA VI News",
        "description": "Official Rockstar update.",
        "url": "https://www.rockstargames.com/newswire/gta-vi-news",
        "datePublished": "2026-09-02T12:00:00Z"
      }
      </script>
    </html>
    """

    result = parse_rockstar_newswire_html(html)

    assert len(result) == 1
    assert result[0].title == "GTA VI News"
    assert result[0].summary == "Official Rockstar update."
    assert result[0].url == (
        "https://www.rockstargames.com/newswire/gta-vi-news"
    )
    assert result[0].source_name == "Rockstar Newswire"
    assert result[0].fact_type == "news"
    assert result[0].confidence == "confirmed"
    assert result[0].published_at == "2026-09-02T12:00:00Z"


def test_parse_rockstar_newswire_html_ignores_non_articles():
    html = """
    <script type="application/ld+json">
    {
      "@type": "WebSite",
      "name": "Rockstar Games"
    }
    </script>
    """

    assert parse_rockstar_newswire_html(html) == []


def test_parse_rockstar_newswire_html_deduplicates_urls():
    payload = """
    {
      "@type": "Article",
      "headline": "Same article",
      "url": "https://www.rockstargames.com/newswire/same"
    }
    """

    html = f"""
    <script type="application/ld+json">{payload}</script>
    <script type="application/ld+json">{payload}</script>
    """

    result = parse_rockstar_newswire_html(html)

    assert len(result) == 1


def test_parse_rockstar_newswire_html_invalid_json_is_ignored():
    html = """
    <script type="application/ld+json">
    { invalid json }
    </script>
    """

    assert parse_rockstar_newswire_html(html) == []
