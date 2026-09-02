from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass


ROCKSTAR_GRAPH_URL = "https://graph.rockstargames.com"
GTA6_NEWSWIRE_TAG_ID = 666
NEWSWIRE_OPERATION = "NewswireList"


@dataclass(frozen=True)
class RockstarNewswireArticle:
    article_id: str
    title: str
    url: str
    created_at: str | None
    tags: tuple[str, ...]
    image_url: str | None


class RockstarNewswireGraphClient:
    def __init__(
        self,
        query_hash: str,
        *,
        timeout: float = 10.0,
    ) -> None:
        if not isinstance(query_hash, str) or not query_hash.strip():
            raise ValueError("query_hash must be a non-empty string")

        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        self.query_hash = query_hash.strip()
        self.timeout = timeout

    def build_url(self) -> str:
        variables = {
            "page": 1,
            "tagId": GTA6_NEWSWIRE_TAG_ID,
            "metaUrl": "/newswire",
            "locale": "en_us",
        }

        extensions = {
            "persistedQuery": {
                "version": 1,
                "sha256Hash": self.query_hash,
            }
        }

        params = urllib.parse.urlencode(
            {
                "operationName": NEWSWIRE_OPERATION,
                "variables": json.dumps(variables, separators=(",", ":")),
                "extensions": json.dumps(
                    extensions,
                    separators=(",", ":"),
                ),
            }
        )

        return f"{ROCKSTAR_GRAPH_URL}?{params}"

    def fetch(self) -> dict:
        request = urllib.request.Request(
            self.build_url(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "BR-no-GTA/1.0",
            },
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
            ) as response:
                body = response.read().decode("utf-8")
        except Exception as exc:
            raise RuntimeError(
                f"Rockstar Newswire Graph request failed: {exc}"
            ) from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Rockstar Newswire Graph returned invalid JSON"
            ) from exc

    def parse_articles(
        self,
        payload: dict,
    ) -> list[RockstarNewswireArticle]:
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dictionary")

        errors = payload.get("errors")
        if errors:
            raise RuntimeError(
                "Rockstar Newswire Graph returned errors"
            )

        data = payload.get("data") or {}
        posts = data.get("posts") or {}
        results = posts.get("results") or []

        if not isinstance(results, list):
            raise ValueError("Newswire results must be a list")

        articles: list[RockstarNewswireArticle] = []

        for item in results:
            if not isinstance(item, dict):
                continue

            article_id = item.get("id")
            title = item.get("title")
            url = item.get("url")

            if article_id is None or not title or not url:
                continue

            tags = tuple(
                tag.get("name")
                for tag in item.get("primary_tags", [])
                if isinstance(tag, dict) and tag.get("name")
            )

            preview_images = item.get("preview_images_parsed") or {}
            newswire_block = preview_images.get("newswire_block") or {}

            articles.append(
                RockstarNewswireArticle(
                    article_id=str(article_id),
                    title=str(title),
                    url=(
                        str(url)
                        if str(url).startswith("http")
                        else f"https://www.rockstargames.com{url}"
                    ),
                    created_at=item.get("created"),
                    tags=tags,
                    image_url=newswire_block.get("d16x9"),
                )
            )

        return articles
