import pytest

from app.services.gta6_editorial_brief_service import (
    GTA6EditorialBrief,
    GTA6EditorialBriefError,
    create_editorial_brief,
    editorial_brief_to_dict,
    validate_editorial_brief,
)


def _create_valid_brief() -> GTA6EditorialBrief:
    return create_editorial_brief(
        topic="sistema policial",
        angle="Por que a polícia de GTA6 parece mais dinâmica?",
        central_question="O que realmente mudou no sistema policial?",
        hook="A polícia de GTA6 pode estar mostrando uma mudança muito maior.",
        facts=[
            "sistema de procurado",
            "perseguições",
            "comportamento policial",
        ],
        evidence_requirements=[
            "perseguição policial",
            "comportamento das autoridades",
            "interação com o jogador",
        ],
        media_requirements=[
            "gameplay policial",
            "footage oficial",
            "análise especializada",
        ],
        target_duration_seconds=900.0,
        priority_score=9.0,
        trend_score=8.5,
    )


def test_create_editorial_brief_returns_valid_contract():
    brief = _create_valid_brief()

    assert isinstance(brief, GTA6EditorialBrief)
    assert brief.topic == "sistema policial"
    assert brief.target_duration_seconds == 900.0
    assert brief.priority_score == 9.0
    assert brief.trend_score == 8.5

    validate_editorial_brief(brief)


def test_editorial_brief_normalizes_text():
    brief = create_editorial_brief(
        topic="  sistema policial  ",
        angle="  Ângulo editorial  ",
        central_question="  Qual é a mudança?  ",
        hook="  Hook GTA6  ",
        facts=["  fato 1  "],
        evidence_requirements=["  evidência 1  "],
        media_requirements=["  gameplay  "],
    )

    assert brief.topic == "sistema policial"
    assert brief.angle == "Ângulo editorial"
    assert brief.central_question == "Qual é a mudança?"
    assert brief.hook == "Hook GTA6"
    assert brief.facts == ("fato 1",)
    assert brief.evidence_requirements == ("evidência 1",)
    assert brief.media_requirements == ("gameplay",)


def test_editorial_brief_serializes_for_next_pipeline():
    brief = _create_valid_brief()

    data = editorial_brief_to_dict(brief)

    assert data["topic"] == "sistema policial"
    assert data["angle"] == (
        "Por que a polícia de GTA6 parece mais dinâmica?"
    )
    assert data["central_question"] == (
        "O que realmente mudou no sistema policial?"
    )
    assert data["facts"] == [
        "sistema de procurado",
        "perseguições",
        "comportamento policial",
    ]
    assert data["evidence_requirements"] == [
        "perseguição policial",
        "comportamento das autoridades",
        "interação com o jogador",
    ]
    assert data["media_requirements"] == [
        "gameplay policial",
        "footage oficial",
        "análise especializada",
    ]


@pytest.mark.parametrize(
    "field",
    [
        "topic",
        "angle",
        "central_question",
        "hook",
    ],
)
def test_editorial_brief_requires_core_text_fields(field):
    values = {
        "topic": "sistema policial",
        "angle": "ângulo",
        "central_question": "pergunta",
        "hook": "hook",
    }

    values[field] = ""

    with pytest.raises(GTA6EditorialBriefError):
        create_editorial_brief(
            **values,
            facts=["fato"],
            evidence_requirements=["evidência"],
            media_requirements=["gameplay"],
        )


def test_editorial_brief_rejects_empty_fact():
    with pytest.raises(GTA6EditorialBriefError):
        create_editorial_brief(
            topic="polícia",
            angle="ângulo",
            central_question="pergunta",
            hook="hook",
            facts=[""],
            evidence_requirements=["evidência"],
            media_requirements=["gameplay"],
        )


def test_editorial_brief_rejects_invalid_priority():
    with pytest.raises(GTA6EditorialBriefError):
        create_editorial_brief(
            topic="polícia",
            angle="ângulo",
            central_question="pergunta",
            hook="hook",
            facts=["fato"],
            evidence_requirements=["evidência"],
            media_requirements=["gameplay"],
            priority_score=11.0,
        )


def test_editorial_brief_rejects_invalid_trend_score():
    with pytest.raises(GTA6EditorialBriefError):
        create_editorial_brief(
            topic="polícia",
            angle="ângulo",
            central_question="pergunta",
            hook="hook",
            facts=["fato"],
            evidence_requirements=["evidência"],
            media_requirements=["gameplay"],
            trend_score=-1.0,
        )


def test_editorial_brief_rejects_non_positive_duration():
    with pytest.raises(GTA6EditorialBriefError):
        create_editorial_brief(
            topic="polícia",
            angle="ângulo",
            central_question="pergunta",
            hook="hook",
            facts=["fato"],
            evidence_requirements=["evidência"],
            media_requirements=["gameplay"],
            target_duration_seconds=0,
        )


def test_editorial_brief_rejects_boolean_score():
    with pytest.raises(GTA6EditorialBriefError):
        create_editorial_brief(
            topic="polícia",
            angle="ângulo",
            central_question="pergunta",
            hook="hook",
            facts=["fato"],
            evidence_requirements=["evidência"],
            media_requirements=["gameplay"],
            priority_score=True,
        )


def test_editorial_brief_validation_rejects_wrong_type():
    with pytest.raises(GTA6EditorialBriefError):
        validate_editorial_brief({"topic": "polícia"})


def test_editorial_brief_is_immutable():
    brief = _create_valid_brief()

    with pytest.raises(AttributeError):
        brief.topic = "outro tópico"
