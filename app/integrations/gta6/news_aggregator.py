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
    """Converte feeds RSS ou Atom em itens normalizados."""

    root = ElementTree.fromstring(xml)

    if _local_name(root.tag) == "feed":
        return _parse_atom_feed(
            root,
            source_name=source_name,
        )

    return _parse_rss_feed(
        root,
        source_name=source_name,
    )


def _parse_rss_feed(
    root,
    *,
    source_name: str,
) -> list[GTA6NewsFeedItem]:
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


def _parse_atom_feed(
    root,
    *,
    source_name: str,
) -> list[GTA6NewsFeedItem]:
    namespace = _namespace(root.tag)

    items: list[GTA6NewsFeedItem] = []

    for element in root.findall(f".//{{{namespace}}}entry"):
        title = _text(element.find(f"{{{namespace}}}title"))
        summary = _text(element.find(f"{{{namespace}}}summary"))
        if not summary:
            summary = _text(element.find(f"{{{namespace}}}content"))

        url = _atom_link(element, namespace)

        published_at = _text(
            element.find(f"{{{namespace}}}published")
        )

        if not published_at:
            published_at = _text(
                element.find(f"{{{namespace}}}updated")
            )

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


def _atom_link(element, namespace: str) -> str:
    links = element.findall(f"{{{namespace}}}link")

    for link in links:
        href = link.get("href")
        relation = link.get("rel")

        if href and relation in (None, "alternate"):
            return href

    return ""


def _namespace(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag[1:tag.index("}")]

    return ""


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]

    return tag


def _text(element) -> str:
    if element is None or element.text is None:
        return ""

    return " ".join(element.text.split())
