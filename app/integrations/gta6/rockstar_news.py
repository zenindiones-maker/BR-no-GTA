from html.parser import HTMLParser
from urllib.request import Request, urlopen

from app.integrations.gta6.source import GTA6SourceItem


ROCKSTAR_NEWSWIRE_URL = "https://www.rockstargames.com/newswire"


class _RockstarLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "a":
            return

        attributes = dict(attrs)
        href = attributes.get("href")

        if href:
            self._current_href = href
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._current_href is None:
            return

        title = " ".join(
            " ".join(self._current_text).split()
        )

        if title:
            self.links.append(
                (
                    title,
                    self._current_href,
                )
            )

        self._current_href = None
        self._current_text = []


def parse_rockstar_newswire_html(
    html: str,
) -> list[GTA6SourceItem]:
    """Extrai candidatos de notícias GTA VI de HTML do Newswire."""

    parser = _RockstarLinkParser()
    parser.feed(html)

    items: list[GTA6SourceItem] = []

    for title, url in parser.links:
        normalized_url = url

        if normalized_url.startswith("/"):
            normalized_url = (
                "https://www.rockstargames.com"
                + normalized_url
            )

        if "grand-theft-auto-vi" not in normalized_url.lower():
            continue

        items.append(
            GTA6SourceItem(
                title=title,
                summary=title,
                url=normalized_url,
                source_name="Rockstar Newswire",
                fact_type="news",
                confidence="confirmed",
            )
        )

    return items


def fetch_rockstar_newswire(
    *,
    timeout: int = 20,
) -> list[GTA6SourceItem]:
    """Busca notícias GTA VI no Rockstar Newswire.

    Falhas de rede são convertidas em RuntimeError para que
    o orquestrador possa tratar a fonte como indisponível.
    """

    request = Request(
        ROCKSTAR_NEWSWIRE_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Linux; Android 10) "
                "AppleWebKit/537.36 "
                "Chrome/120 Safari/537.36"
            )
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            html = response.read().decode(
                "utf-8",
                errors="replace",
            )
    except Exception as exc:
        raise RuntimeError(
            "failed to fetch Rockstar Newswire"
        ) from exc

    return parse_rockstar_newswire_html(html)
