import pytest

from app.integrations.gta6.news_feeds import (
    fetch_gta6_news_feeds,
    fetch_news_feed,
)


def test_fetch_news_feed(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"""
            <rss>
              <channel>
                <item>
                  <title>GTA VI News</title>
                  <description>New information.</description>
                  <link>https://example.com/gta6</link>
                  <pubDate>2026-09-02</pubDate>
                </item>
              </channel>
            </rss>
            """

    def fake_urlopen(request, timeout):
        assert request.full_url == "https://example.com/feed"
        assert timeout == 5
        return FakeResponse()

    monkeypatch.setattr(
        "app.integrations.gta6.news_feeds.urlopen",
        fake_urlopen,
    )

    result = fetch_news_feed(
        source_name="Test",
        url="https://example.com/feed",
        timeout=5,
    )

    assert len(result) == 1
    assert result[0].title == "GTA VI News"
    assert result[0].source_name == "Test"


def test_fetch_news_feed_failure(monkeypatch):
    def fake_urlopen(request, timeout):
        raise OSError("network error")

    monkeypatch.setattr(
        "app.integrations.gta6.news_feeds.urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        RuntimeError,
        match="failed to fetch news feed: Test",
    ):
        fetch_news_feed(
            source_name="Test",
            url="https://example.com/feed",
        )


def test_fetch_gta6_news_feeds(monkeypatch):
    calls = []

    def fake_fetch_news_feed(
        *,
        source_name,
        url,
        timeout,
    ):
        calls.append((source_name, url, timeout))
        return []

    monkeypatch.setattr(
        "app.integrations.gta6.news_feeds.fetch_news_feed",
        fake_fetch_news_feed,
    )

    result = fetch_gta6_news_feeds(timeout=7)

    assert result == []
    assert len(calls) == 2
    assert all(call[2] == 7 for call in calls)
