"""Claims das fontes oficiais (PS Store, Xbox, Take-Two) chegam ao fact-check
com suporte oficial e a URL de origem — antes só 4 frases da página Rockstar."""
from __future__ import annotations

from app.services import telegram_source_intelligence_service as svc

PS = "https://www.playstation.com/pt-br/games/grand-theft-auto-vi/"


def _packet():
    statement = "Standard Edition: Grand Theft Auto VI · Pacote Vintage Vice City · Um mês de GTA+ · Pré-carregamento 7 dias antes — R$449,90"
    return statement, {
        "submitted_source": {
            "resolution_status": "PASS", "url": "https://www.rockstargames.com/VI",
            "source_hierarchy": "OFFICIAL_PRIMARY",
            "content_excerpt": "Grand Theft Auto VI Coming November 19, 2026 PlayStation 5 Xbox Series X|S",
        },
        "official_sources": [{
            "url": PS, "content_excerpt": statement + " Grand Theft Auto VI será lançado em 19 de novembro de 2026.",
        }],
        "official_claims": [
            {"statement": statement, "source_url": PS, "kind": "edition_offer"},
            {"statement": statement, "source_url": PS, "kind": "edition_offer"},
        ],
    }


def test_packet_claims_merge_submitted_and_official_without_duplicates():
    statement, packet = _packet()
    claims = svc._packet_claims(packet)
    assert statement in claims
    assert claims.count(statement) == 1
    assert any("November 19, 2026" in c for c in claims)
    assert len(claims) <= svc.MAX_PACKET_CLAIMS


def test_official_claim_gets_official_support_and_source_url():
    statement, packet = _packet()
    evidence, hierarchy = svc._evidence_for_claim(statement, packet)
    assert hierarchy["official_support"] is True
    assert any(e["source_ref"] == PS and e["stance"] == "supporting" for e in evidence)
