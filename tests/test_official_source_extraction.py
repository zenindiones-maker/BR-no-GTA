"""Pesquisador lê TODAS as fontes oficiais informadas (Luiz, 18/10/2026 23:22).

Cada claim sai com a URL oficial de onde foi extraída; fatos do Brasil
(preço em R$, edições, pré-carregamento, GTA+) viram evidência quando a página
oficial os traz. Páginas JS-heavy usam fallback estático, JSON-LD, meta e JSON
embutido — custo zero, sem API paga.
"""
from __future__ import annotations

from pathlib import Path

from app.services import official_source_extraction as ext
from scripts import gta6_fresh_research_worker as worker

FIX = Path(__file__).parent / "fixtures" / "official_pages"
PS = "https://www.playstation.com/pt-br/games/grand-theft-auto-vi/"
XBOX = "https://www.xbox.com/pt-BR/games/grand-theft-auto-vi"
T2 = "https://www.take2games.com/"
NEWS = "https://www.rockstargames.com/newswire"


def _html(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _statements(result: dict) -> list[str]:
    return [c["statement"] for c in result["claims"]]


def test_official_domains_include_platform_stores_only():
    for url in (PS, XBOX, T2, NEWS, "https://store.playstation.com/pt-br/product/x",
                "https://www.rockstargames.com/VI"):
        assert ext.is_official_url(url), url
    for url in ("https://www.ign.com/gta6", "https://playstation.com.evil.example/x",
                "http://www.rockstargames.com/VI"):
        assert not ext.is_official_url(url), url


def test_playstation_brl_prices_editions_preload_and_gtaplus_become_claims():
    result = ext.extract_official_evidence(_html("playstation_gta6_ptbr.html"), PS)
    claims = result["claims"]
    assert claims and all(c["source_url"] == PS for c in claims)
    joined = "\n".join(_statements(result))
    assert "R$449,90" in joined and "Standard Edition" in joined
    assert "R$549,90" in joined and "Ultimate Edition" in joined
    assert "Pré-carregamento 7 dias antes" in joined
    assert "GTA+" in joined
    assert "19 de novembro de 2026" in joined
    # JSON-LD estruturado (offers em BRL) vira evidência.
    assert any(c["kind"] == "json_ld" and "549,90" in c["statement"] and "BRL" in c["statement"]
               for c in claims)
    # Script comum (analytics) nunca vira evidência.
    assert "Red Dead" not in joined and "R$ 1,00" not in joined
    # Cada claim está literalmente no excerpt da fonte (fact-check por sobreposição).
    for statement in _statements(result):
        assert statement in result["content_excerpt"], statement


def test_xbox_meta_and_static_text_become_claims():
    result = ext.extract_official_evidence(_html("xbox_gta6_ptbr.html"), XBOX)
    joined = "\n".join(_statements(result))
    assert "19 de novembro de 2026" in joined and "XBOX Series X|S" in joined
    assert all(c["source_url"] == XBOX for c in result["claims"])


def test_take_two_embedded_json_extracts_only_gta_vi_items():
    result = ext.extract_official_evidence(_html("take2_home.html"), T2)
    joined = "\n".join(_statements(result))
    assert "Rockstar Games Releases Trailer 2 for Grand Theft Auto VI" in joined
    assert "2025-05-06" in joined
    assert "NBA 2K27" not in joined and "Fiscal Second Quarter" not in joined


def test_js_shell_falls_back_to_meta_without_inventing_claims():
    result = ext.extract_official_evidence(_html("rockstar_newswire_shell.html"), NEWS)
    assert result["extraction_methods"]["meta"] >= 1
    assert result["claims"] == []  # nada sobre GTA VI na casca JS: nenhum claim inventado


def test_collect_fetches_every_official_url_with_per_claim_source(monkeypatch):
    pages = {PS: "playstation_gta6_ptbr.html", XBOX: "xbox_gta6_ptbr.html", T2: "take2_home.html"}
    fetched: list[str] = []

    def fake_raw(url, *, timeout=25):
        fetched.append(url)
        return _html(pages[url]), url

    monkeypatch.setattr(worker, "_fetch_raw", fake_raw)
    monkeypatch.setattr(worker, "fetch_gta6_news_feeds", lambda timeout=20: [])
    monkeypatch.setattr(worker, "_fetch_text", lambda url, timeout=25: (_ for _ in ()).throw(AssertionError(url)))
    out = worker.collect(
        "Guia oficial",
        execution_id="t",
        official_source_urls=[PS, XBOX, T2, "https://www.ign.com/gta6"],
    )
    assert fetched == [PS, XBOX, T2]
    assert out["status"] == "PASS"
    assert [s["url"] for s in out["official_sources"]] == [PS, XBOX, T2]
    for source in out["official_sources"]:
        assert source["source_hierarchy"] == "OFFICIAL_PRIMARY"
        assert source["claims"] and all(c["source_url"] == source["url"] for c in source["claims"])
    flat = out["official_claims"]
    assert {c["source_url"] for c in flat} == {PS, XBOX, T2}
    assert any("R$449,90" in c["statement"] for c in flat)
    assert any(e["url"] == "https://www.ign.com/gta6" and e["error"] == "NOT_AN_OFFICIAL_SOURCE"
               for e in out["source_errors"])


def test_worker_cli_accepts_official_urls_b64():
    body = Path(worker.__file__).read_text(encoding="utf-8")
    assert "--official-urls-b64" in body
