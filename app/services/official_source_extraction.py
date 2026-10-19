"""Extração determinística de evidência de páginas oficiais (custo zero).

Diretriz do Luiz (18/10/2026 23:22): o pesquisador lê TODAS as fontes oficiais
informadas (Rockstar, PlayStation Store, Xbox, Take-Two) e cada claim sai com a
URL de onde veio. Páginas JS-heavy: fallback estático (texto servido), dados
estruturados (JSON-LD), meta tags e JSON embutido (__NEXT_DATA__). Sem API paga,
sem navegador, sem inventar: todo claim é texto literal (ou campo estruturado)
da própria página.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
from typing import Any, Iterable

OFFICIAL_DOMAINS = (
    "rockstargames.com",
    "take2games.com",
    "take2.com",
    "playstation.com",
    "xbox.com",
)
MAX_CLAIMS_PER_SOURCE = 40
MAX_EXCERPT_CHARS = 16000

_GTA_TERMS = (
    "grand theft auto", "gta", "gtavi", "leonida", "vice city", "jason", "lucia",
)
_BOILERPLATE = (
    "skip to main content", "pular para o conteúdo", "ir para o conteúdo",
    "expandir menu", "expand navigation", "adicionar à lista de desejos",
    "cookie", "política de privacidade", "privacy policy", "termos de uso",
    "terms of use", "mapa do site", "role para ver mais", "scroll for more",
    "see all", "ver todos", "learn more", "saiba mais",
    "marcas comerciais", "trademarks", "all rights reserved", "todos os direitos",
)
_BLOCK_TAGS = r"p|div|li|ul|ol|h[1-6]|br|tr|td|th|section|article|header|footer|nav|dt|dd|table|main|aside|button"
_EDITION_RE = re.compile(
    r"\b((?:Standard|Ultimate|Deluxe|Gold|Premium|Special|Collector'?s?)\s+Edition)\b",
)
_PRICE_RE = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*,\d{2}")


def is_official_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.rstrip(".").casefold()
    return any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)


def _gta_relevant(text: str) -> bool:
    folded = text.casefold()
    return any(term in folded for term in _GTA_TERMS)


def _clean(text: str) -> str:
    return " ".join(html.unescape(str(text or "")).split())


def _scripts(raw: str, kind_pattern: str) -> list[str]:
    return [
        m.group(1)
        for m in re.finditer(
            r"<script\b[^>]*" + kind_pattern + r"[^>]*>(.*?)</script>",
            raw,
            flags=re.I | re.S,
        )
    ]


def _visible_lines(raw: str) -> list[str]:
    body = re.sub(r"<(script|style|noscript|template|svg)\b[^>]*>.*?</\1>", " ", raw, flags=re.I | re.S)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    body = re.sub(r"<head\b[^>]*>.*?</head>", " ", body, flags=re.I | re.S)
    body = re.sub(r"</?(?:" + _BLOCK_TAGS + r")\b[^>]*>", "\n", body, flags=re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    lines = [_clean(line) for line in html.unescape(body).split("\n")]
    return [line for line in lines if line]


def _meta(raw: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    title = re.search(r"<title\b[^>]*>(.*?)</title>", raw, flags=re.I | re.S)
    if title and _clean(title.group(1)):
        found.append(("title", _clean(title.group(1))))
    for tag in re.findall(r"<meta\b[^>]*>", raw, flags=re.I):
        key = re.search(r"\b(?:name|property)\s*=\s*\"([^\"]+)\"", tag, flags=re.I)
        content = re.search(r"\bcontent\s*=\s*\"([^\"]*)\"", tag, flags=re.I)
        if not key or not content:
            continue
        name = key.group(1).casefold()
        if name in {"description", "og:description", "og:title", "twitter:description", "twitter:title"}:
            value = _clean(content.group(1))
            if value:
                found.append((name, value))
    return found


def _walk(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _brl(price: Any) -> str:
    value = float(price)
    whole, cents = f"{value:.2f}".split(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return f"R$ {'.'.join(groups)},{cents}"


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!])\s+|\n+", text) if s.strip()]


def _json_ld_claims(raw: str) -> list[str]:
    out: list[str] = []
    for block in _scripts(raw, r"application/ld\+json"):
        try:
            data = json.loads(html.unescape(block).strip())
        except ValueError:
            continue
        for node in _walk(data):
            name = _clean(node.get("name") or "")
            offers = node.get("offers")
            if name and isinstance(offers, (dict, list)):
                for offer in offers if isinstance(offers, list) else [offers]:
                    if not isinstance(offer, dict) or offer.get("price") in (None, ""):
                        continue
                    currency = str(offer.get("priceCurrency") or "").upper()
                    try:
                        price = _brl(offer["price"]) if currency == "BRL" else f"{offer['price']} {currency}".strip()
                    except (TypeError, ValueError):
                        continue
                    if _gta_relevant(name):
                        out.append(f"{name} — {price} ({currency or 'moeda não informada'})")
            if name and _gta_relevant(name) and node.get("uploadDate"):
                out.append(f"Vídeo oficial \"{name}\" publicado em {str(node['uploadDate'])[:10]}")
            description = str(node.get("description") or "")
            if name and description and _gta_relevant(name):
                for sentence in _sentences(description):
                    if "http" in sentence or sentence.startswith("#") or len(sentence) < 30:
                        continue
                    if _gta_relevant(sentence):
                        out.append(_clean(sentence))
    return out


def _embedded_json_claims(raw: str) -> list[str]:
    out: list[str] = []
    for block in _scripts(raw, r"(?:__NEXT_DATA__|application/json)"):
        try:
            data = json.loads(html.unescape(block).strip())
        except ValueError:
            continue
        for node in _walk(data):
            title = node.get("title")
            if not isinstance(title, str) or not re.search(r"grand theft auto vi\b|\bgta\s?vi\b", title, re.I):
                continue
            if len(title.split()) < 4 or re.search(r"\d+x\d+", title):
                continue  # nomes de imagem/asset, não notícia
            date = str(node.get("releaseDate") or node.get("date") or node.get("publishedAt") or "")[:10]
            out.append(f"{_clean(title)} ({date})" if re.match(r"\d{4}-\d{2}-\d{2}", date) else _clean(title))
    return out


def _edition_offer_claims(lines: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        editions = _EDITION_RE.findall(line)
        if editions and line.rstrip().endswith("Edition") and not _PRICE_RE.search(line):
            edition = editions[-1]
            items: list[str] = []
            j = i + 1
            price = None
            while j < len(lines) and j <= i + 12:
                match = _PRICE_RE.search(lines[j])
                if match:
                    price = match.group(0)
                    break
                if lines[j] != edition:
                    items.append(lines[j])
                j += 1
            if price and items:
                out.append(f"{edition}: {' · '.join(items)} — {price}")
                i = j + 1
                continue
        i += 1
    return out


def _sentence_claims(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            sentence = sentence.strip()
            if len(sentence) < 30 or len(sentence) > 420 or sentence.endswith("?"):
                continue
            folded = sentence.casefold()
            if any(marker in folded for marker in _BOILERPLATE):
                continue
            if not _gta_relevant(sentence):
                continue
            has_fact = bool(_PRICE_RE.search(sentence) or re.search(r"\b\d{1,2} de [a-zç]+ de \d{4}\b|\b\d{4}\b", sentence))
            if not sentence.endswith((".", "!")) and not has_fact:
                continue  # título/menu solto, não afirmação
            out.append(sentence)
    return out


def extract_official_evidence(raw_html: str, url: str) -> dict[str, Any]:
    raw = str(raw_html or "")
    lines = _visible_lines(raw)
    meta = _meta(raw)
    offers = _edition_offer_claims(lines)
    json_ld = _json_ld_claims(raw)
    embedded = _embedded_json_claims(raw)
    meta_claims = [value for _key, value in meta if _gta_relevant(value) and len(value) >= 30]
    sentences = _sentence_claims(lines)

    claims: list[dict[str, str]] = []
    seen: set[str] = set()
    for kind, statements in (
        ("edition_offer", offers),
        ("json_ld", json_ld),
        ("embedded_json", embedded),
        ("static_text", sentences),
        ("meta", meta_claims),
    ):
        for statement in statements:
            key = statement.casefold()
            if not statement or key in seen or any(key in other for other in seen):
                continue
            seen.add(key)
            claims.append({"statement": statement, "source_url": url, "kind": kind})
    claims = claims[:MAX_CLAIMS_PER_SOURCE]
    visible = " ".join(lines)
    header = "\n".join(c["statement"] for c in claims)
    meta_text = "\n".join(value for _key, value in meta)
    excerpt = "\n".join(part for part in (header, meta_text, visible) if part)[:MAX_EXCERPT_CHARS]
    return {
        "source_url": url,
        "claims": claims,
        "content_excerpt": excerpt,
        "visible_text_chars": len(visible),
        "extraction_methods": {
            "static_text": len(sentences),
            "edition_offers": len(offers),
            "json_ld": len(json_ld),
            "embedded_json": len(embedded),
            "meta": len(meta),
        },
    }
