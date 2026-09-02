from app.integrations.gta6.news_aggregator import (
    parse_rss_feed,
)


def test_parse_rss_feed():
    xml = """
    <rss>
        <channel>
            <item>
                <title>GTA VI News</title>
                <description>
                    New GTA VI information.
                </description>
                <link>
                    https://example.com/gta6/news
                </link>
                <pubDate>
                    Tue, 02 Sep 2026 00:00:00 GMT
                </pubDate>
            </item>
        </channel>
    </rss>
    """

    items = parse_rss_feed(
        xml,
        source_name="Test Source",
    )

    assert len(items) == 1

    item = items[0]

    assert item.title == "GTA VI News"
    assert item.summary == "New GTA VI information."
    assert item.url == "https://example.com/gta6/news"
    assert item.source_name == "Test Source"
    assert item.published_at == (
        "Tue, 02 Sep 2026 00:00:00 GMT"
    )


def test_parse_rss_feed_ignores_incomplete_items():
    xml = """
    <rss>
        <channel>
            <item>
                <title>Missing URL</title>
                <description>Ignored.</description>
            </item>

            <item>
                <link>https://example.com/no-title</link>
            </item>

            <item>
                <title>Valid GTA VI</title>
                <link>https://example.com/gta6</link>
            </item>
        </channel>
    </rss>
    """

    items = parse_rss_feed(
        xml,
        source_name="Test Source",
    )

    assert len(items) == 1
    assert items[0].title == "Valid GTA VI"


def test_parse_rss_feed_unescapes_html_entities():
    xml = """
    <rss>
        <channel>
            <item>
                <title>GTA VI &amp; Vice City</title>
                <description>
                    Tom &amp; Lucia
                </description>
                <link>https://example.com/gta6</link>
            </item>
        </channel>
    </rss>
    """

    items = parse_rss_feed(
        xml,
        source_name="Test Source",
    )

    assert items[0].title == "GTA VI & Vice City"
    assert items[0].summary == "Tom & Lucia"


def test_parse_rss_feed_empty():
    xml = """
    <rss>
        <channel />
    </rss>
    """

    assert parse_rss_feed(
        xml,
        source_name="Test Source",
    ) == []


def test_parse_atom_feed():
    xml = """
    <feed xmlns="http://www.w3.org/2005/Atom">
        <entry>
            <title>GTA VI Atom News</title>
            <summary>New GTA VI information.</summary>
            <link href="https://example.com/gta6/atom" />
            <published>2026-09-02T00:00:00Z</published>
        </entry>
    </feed>
    """

    items = parse_rss_feed(
        xml,
        source_name="Atom Source",
    )

    assert len(items) == 1

    item = items[0]

    assert item.title == "GTA VI Atom News"
    assert item.summary == "New GTA VI information."
    assert item.url == "https://example.com/gta6/atom"
    assert item.source_name == "Atom Source"
    assert item.published_at == "2026-09-02T00:00:00Z"
