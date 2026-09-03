import pytest

from app.services.gta6_media_intelligence_service import (
    GTA6MediaIntelligence,
    GTA6MediaIntelligenceError,
    evaluate_gta6_media_intelligence,
    rank_gta6_media_by_intelligence,
)


def _official_candidate():
    return {
        "video_id": "official-police",
        "title": "Grand Theft Auto VI: Official Police Gameplay",
        "description": (
            "Official GTA VI gameplay showing police chase mechanics."
        ),
        "source_authority": "official",
        "gta6_relevant": True,
        "published_at": "2026-09-03T00:00:00Z",
        "relevance_score": 7.5,
    }


def _community_candidate():
    return {
        "video_id": "community-analysis",
        "title": (
            "O NOVO Sistema de Polícia do GTA 6 Vai MUDAR MUITO"
        ),
        "description": (
            "Análise completa das novas perseguições "
            "e mecânicas policiais."
        ),
        "source_authority": "community",
        "gta6_relevant": True,
        "published_at": "2026-09-02T20:00:00Z",
        "relevance_score": 7.5,
    }


def test_returns_intelligence_contract():
    result = evaluate_gta6_media_intelligence(
        _official_candidate(),
        topic="polícia",
        trending_topics=["sistema policial"],
    )

    assert isinstance(
        result,
        GTA6MediaIntelligence,
    )


def test_official_source_has_strong_evidence_score():
    result = evaluate_gta6_media_intelligence(
        _official_candidate(),
        topic="polícia",
    )

    assert result.authority_score == 10.0
    assert result.evidence_score >= 8.0


def test_editorial_opportunity_is_separate_from_evidence():
    official = evaluate_gta6_media_intelligence(
        _official_candidate(),
        topic="polícia",
    )

    community = evaluate_gta6_media_intelligence(
        _community_candidate(),
        topic="polícia",
        trending_topics=["sistema policial"],
    )

    assert official.evidence_score > community.evidence_score
    assert community.opportunity_score > 0
    assert official.opportunity_score > 0


def test_media_role_is_not_hybrid():
    official = evaluate_gta6_media_intelligence(
        _official_candidate(),
        topic="polícia",
    )

    community = evaluate_gta6_media_intelligence(
        _community_candidate(),
        topic="polícia",
    )

    assert official.media_role in {
        "gameplay",
        "footage",
        "analysis",
        "unknown",
    }

    assert community.media_role in {
        "gameplay",
        "footage",
        "analysis",
        "unknown",
    }

    assert official.editorial_role in {
        "primary_evidence",
        "visual_evidence",
        "context",
        "discovery",
    }


def test_official_source_can_be_primary_evidence():
    result = evaluate_gta6_media_intelligence(
        _official_candidate(),
        topic="polícia",
    )

    assert result.editorial_role == "primary_evidence"


def test_trend_language_is_not_proof_of_trend():
    candidate = _community_candidate()

    without_trending_data = evaluate_gta6_media_intelligence(
        candidate,
        topic="polícia",
        trending_topics=None,
    )

    with_trending_data = evaluate_gta6_media_intelligence(
        candidate,
        topic="polícia",
        trending_topics=["sistema policial"],
    )

    assert (
        with_trending_data.trend_relevance
        >= without_trending_data.trend_relevance
    )


def test_rejects_non_gta6_media():
    candidate = {
        "video_id": "old-gta",
        "title": "GTA V Police Chase",
        "description": "Gameplay de perseguição policial.",
        "source_authority": "community",
        "gta6_relevant": False,
    }

    with pytest.raises(GTA6MediaIntelligenceError):
        evaluate_gta6_media_intelligence(
            candidate,
            topic="polícia",
        )


def test_rank_preserves_candidates_and_adds_intelligence():
    candidates = [
        _official_candidate(),
        _community_candidate(),
    ]

    ranked = rank_gta6_media_by_intelligence(
        candidates,
        topic="polícia",
        trending_topics=["sistema policial"],
    )

    assert len(ranked) == 2
    assert all(
        "intelligence_score" in item
        for item in ranked
    )

    assert all(
        "evidence_score" in item
        for item in ranked
    )

    assert all(
        "opportunity_score" in item
        for item in ranked
    )

    assert all(
        "editorial_role" in item
        for item in ranked
    )


def test_rank_does_not_mutate_original_candidate():
    candidate = _official_candidate()

    original_keys = set(candidate)

    rank_gta6_media_by_intelligence(
        [candidate],
        topic="polícia",
    )

    assert set(candidate) == original_keys
    assert "intelligence_score" not in candidate


def test_reasons_are_explainable():
    result = evaluate_gta6_media_intelligence(
        _official_candidate(),
        topic="polícia",
    )

    assert result.reasons
    assert all(
        isinstance(reason, str)
        and reason.strip()
        for reason in result.reasons
    )


def test_scores_stay_between_zero_and_ten():
    results = [
        evaluate_gta6_media_intelligence(
            _official_candidate(),
            topic="polícia",
        ),
        evaluate_gta6_media_intelligence(
            _community_candidate(),
            topic="polícia",
            trending_topics=["sistema policial"],
        ),
    ]

    for result in results:
        for value in (
            result.topic_relevance,
            result.trend_relevance,
            result.opportunity_score,
            result.evidence_score,
            result.authority_score,
            result.freshness_score,
            result.visual_value,
            result.information_value,
            result.editorial_relevance,
            result.total_score,
        ):
            assert 0.0 <= value <= 10.0


def test_invalid_candidate_type_is_rejected():
    with pytest.raises(GTA6MediaIntelligenceError):
        evaluate_gta6_media_intelligence(
            "invalid",
        )


def test_invalid_candidates_collection_is_rejected():
    with pytest.raises(GTA6MediaIntelligenceError):
        rank_gta6_media_by_intelligence(
            "invalid",
        )


def test_official_evidence_is_higher_than_community_evidence():
    official = evaluate_gta6_media_intelligence(
        _official_candidate(),
        topic="polícia",
    )

    community = evaluate_gta6_media_intelligence(
        _community_candidate(),
        topic="polícia",
    )

    assert official.evidence_score > community.evidence_score
