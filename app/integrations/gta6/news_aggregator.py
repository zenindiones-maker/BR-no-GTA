from dataclasses import dataclass
from html import unescape
from xml.etree import ElementTree


@dataclass(frozen=True)
class GTA6NewsFeedItem:
    title: str
    summary: str
    url: str
    source_name: str
    published_at: str | None = None


def parse_rss_feed(
    xml: str,
    *,
    source_name: str,
) -> list[GTA6NewsFeedItem]:
    """Converte um RSS/Atom simples em itens normalizados."""

    root = ElementTree.fromstring(xml)

    items: list[GTA6NewsFeedItem] = []

    for element in root.findall(".//item"):
        title = _text(element.find("title"))
        summary = _text(element.find("description"))
        url = _text(element.find("link"))
        published_at = _text(element.find("pubDate"))

        if not title or not url:
            continue

        items.append(
            GTA6NewsFeedItem(
                title=unescape(title),
                summary=unescape(summary),
                url=url,
                source_name=source_name,
                published_at=published_at or None,
            )
        )

    return items


def _text(element) -> str:
    if element is None or element.text is None:
        return ""

    return " ".join(element.text.split())
