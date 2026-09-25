import pytest

from app.database.ideas_repository import insert_idea
from app.database.research_repository import insert_research_item
from app.database.schema import initialize_schema
from app.services.script_generator_service import (
    generate_and_save_script,
    generate_script_structure,
)


def test_generate_script_structure_from_approved_idea():
    initialize_schema()

    idea_id = insert_idea(
        title="GTA 6 pode mudar a forma como jogamos no modo online",
        description="Novos sistemas podem alterar profundamente a experiência.",
        status="approved",
        score=9.5,
    )

    structure = generate_script_structure(idea_id)

    assert structure["title"] == (
        "GTA 6 pode mudar a forma como jogamos no modo online"
    )
    assert structure["hook"]
    assert structure["introduction"]
    assert structure["development"]
    assert structure["conclusion"]
    assert structure["cta"]


def test_generate_script_structure_uses_research_context():
    initialize_schema()

    research_id = insert_research_item(
        source_id=None,
        title="Novos detalhes sobre GTA 6",
        content="A Rockstar revelou novos elementos da experiência online.",
        url="https://example.com/gta6",
    )

    idea_id = insert_idea(
        title="O que os novos detalhes revelam sobre GTA 6",
        description="Precisamos analisar o impacto dessas informações.",
        status="approved",
        score=9.0,
        research_item_id=research_id,
    )

    structure = generate_script_structure(idea_id)

    assert structure["research_context"] is not None
    assert structure["research_context"]["title"] == (
        "Novos detalhes sobre GTA 6"
    )
    assert "Rockstar" in structure["research_context"]["content"]


def test_cannot_generate_script_for_unapproved_idea():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - ideia não aprovada",
        description="Descrição.",
        status="new",
        score=7.0,
    )

    with pytest.raises(ValueError, match="ideia aprovada"):
        generate_script_structure(idea_id)


def test_cannot_generate_script_for_nonexistent_idea():
    initialize_schema()

    with pytest.raises(ValueError, match="não existe"):
        generate_script_structure(999999)


def test_generate_script_structure_requires_usable_description():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - sem descrição",
        description="",
        status="approved",
        score=8.0,
    )

    with pytest.raises(ValueError, match="descrição"):
        generate_script_structure(idea_id)


def test_development_has_editorial_sections():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - estrutura editorial",
        description="Uma pauta que precisa ser desenvolvida.",
        status="approved",
        score=8.5,
    )

    structure = generate_script_structure(idea_id)

    assert isinstance(structure["development"], list)
    assert len(structure["development"]) >= 3

    for section in structure["development"]:
        assert "heading" in section
        assert "body" in section
        assert section["heading"]
        assert section["body"]


def test_generate_and_save_script_persists_draft():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - geração persistida",
        description="Uma pauta aprovada para gerar um roteiro.",
        status="approved",
        score=9.0,
    )

    from app.services.script_generator_service import (
        generate_and_save_script,
    )
    from app.database.scripts_repository import get_latest_script_by_idea

    script_id = generate_and_save_script(idea_id)

    script = get_latest_script_by_idea(idea_id)

    assert script is not None
    assert script["id"] == script_id
    assert script["idea_id"] == idea_id
    assert script["status"] == "draft"
    assert script["version"] == 1
    assert script["title"] == "TESTE - geração persistida"
    assert script["content"]


def test_generate_and_save_script_creates_new_version():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - versões persistidas",
        description="Uma pauta para testar versões.",
        status="approved",
        score=9.0,
    )

    from app.services.script_generator_service import (
        generate_and_save_script,
    )
    from app.database.scripts_repository import (
        get_latest_script_by_idea,
    )

    first_id = generate_and_save_script(idea_id)
    second_id = generate_and_save_script(idea_id)

    latest = get_latest_script_by_idea(idea_id)

    assert latest is not None
    assert latest["id"] == second_id
    assert second_id != first_id
    assert latest["version"] == 2


def test_generate_and_save_script_rejects_unapproved_idea():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - não aprovada",
        description="Descrição.",
        status="new",
        score=7.0,
    )

    from app.services.script_generator_service import (
        generate_and_save_script,
    )

    with pytest.raises(ValueError, match="ideia aprovada"):
        generate_and_save_script(idea_id)


def test_generate_script_structure_uses_ai_provider():
    from app.services.fake_ai_provider import FakeAIProvider

    initialize_schema()

    idea_id = insert_idea(
        title="GTA 6 terá uma grande novidade online",
        description="A experiência online pode receber mudanças importantes.",
        status="approved",
        score=9.5,
    )

    provider = FakeAIProvider(
        response=(
            '{"hook":"HOOK IA",'
            '"introduction":"INTRO IA",'
            '"development":['
            '{"heading":"Contexto IA","body":"CONTEXTO IA"},'
            '{"heading":"Novidade IA","body":"NOVIDADE IA"},'
            '{"heading":"Impacto IA","body":"IMPACTO IA"}'
            '],'
            '"conclusion":"CONCLUSÃO IA",'
            '"cta":"CTA IA"}'
        )
    )

    structure = generate_script_structure(
        idea_id,
        ai_provider=provider,
    )

    assert structure["title"] == (
        "GTA 6 terá uma grande novidade online"
    )
    assert structure["hook"] == "HOOK IA"
    assert structure["introduction"] == "INTRO IA"
    assert structure["development"][0]["heading"] == "Contexto IA"
    assert structure["development"][0]["body"] == "CONTEXTO IA"
    assert structure["conclusion"] == "CONCLUSÃO IA"
    assert structure["cta"] == "CTA IA"

    assert len(provider.prompts) == 1
    assert "GTA 6 terá uma grande novidade online" in provider.prompts[0]
    assert "experiência online" in provider.prompts[0]


def test_generate_script_structure_rejects_invalid_ai_json():
    from app.services.fake_ai_provider import FakeAIProvider
    from app.services.ai_provider import AIProviderError

    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - JSON inválido",
        description="Descrição válida.",
        status="approved",
        score=9.0,
    )

    provider = FakeAIProvider(
        response="não é json"
    )

    with pytest.raises(
        AIProviderError,
        match="invalid JSON",
    ):
        generate_script_structure(
            idea_id,
            ai_provider=provider,
        )


def test_generate_and_save_script_uses_ai_provider():
    from app.services.fake_ai_provider import FakeAIProvider
    from app.database.scripts_repository import (
        get_latest_script_by_idea,
    )

    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - roteiro IA persistido",
        description="Descrição para geração por IA.",
        status="approved",
        score=9.5,
    )

    provider = FakeAIProvider(
        response=(
            '{"hook":"HOOK IA",'
            '"introduction":"INTRO IA",'
            '"development":['
            '{"heading":"A","body":"B"},'
            '{"heading":"C","body":"D"},'
            '{"heading":"E","body":"F"}'
            '],'
            '"conclusion":"CONCLUSÃO IA",'
            '"cta":"CTA IA"}'
        )
    )

    script_id = generate_and_save_script(
        idea_id,
        ai_provider=provider,
    )

    script = get_latest_script_by_idea(idea_id)

    assert script is not None
    assert script["id"] == script_id
    assert script["title"] == "TESTE - roteiro IA persistido"
    assert script["status"] == "draft"
    assert "HOOK IA" in script["content"]
    assert "INTRO IA" in script["content"]
    assert "CONCLUSÃO IA" in script["content"]
    assert "CTA IA" in script["content"]


def test_generate_script_structure_accepts_fenced_ai_json():
    from app.services.fake_ai_provider import FakeAIProvider

    initialize_schema()
    idea_id = insert_idea(
        title="TESTE - JSON fenced",
        description="Descrição válida.",
        status="approved",
        score=9.0,
    )
    payload = (
        '{"hook":"HOOK IA","introduction":"INTRO IA","development":['
        '{"heading":"A","body":"B"},{"heading":"C","body":"D"},'
        '{"heading":"E","body":"F"}],"conclusion":"CONCLUSÃO IA","cta":"CTA IA"}'
    )
    provider = FakeAIProvider(response="\uFEFF```json\n" + payload + "\n```")
    structure = generate_script_structure(idea_id, ai_provider=provider)
    assert structure["hook"] == "HOOK IA"
    assert structure["development"][2]["heading"] == "E"


def test_generate_script_structure_rejects_prose_around_json():
    from app.services.fake_ai_provider import FakeAIProvider
    from app.services.ai_provider import AIProviderError

    initialize_schema()
    idea_id = insert_idea(
        title="TESTE - prosa extra",
        description="Descrição válida.",
        status="approved",
        score=9.0,
    )
    payload = (
        '{"hook":"HOOK IA","introduction":"INTRO IA","development":['
        '{"heading":"A","body":"B"},{"heading":"C","body":"D"},'
        '{"heading":"E","body":"F"}],"conclusion":"CONCLUSÃO IA","cta":"CTA IA"}'
    )
    provider = FakeAIProvider(response="Aqui está o JSON:\n" + payload)
    with pytest.raises(AIProviderError, match="invalid JSON"):
        generate_script_structure(idea_id, ai_provider=provider)

def test_longform_script_retries_once_until_voice_b_duration_is_supported():
    import json

    from app.services.ai_provider import AIResponse

    initialize_schema()
    idea_id = insert_idea(
        title="TESTE - longform profissional",
        description="Pauta factual com material suficiente para análise detalhada.",
        status="approved",
        score=9.5,
    )

    short = {
        "hook": "hook curto",
        "introduction": "intro curta",
        "development": [
            {"heading": f"Bloco {index}", "body": "conteudo curto"}
            for index in range(8)
        ],
        "conclusion": "conclusao curta",
        "cta": "cta curta",
    }
    long_body = " ".join(["evidencia"] * 335)
    long = {
        "hook": " ".join(["evidencia"] * 80),
        "introduction": " ".join(["evidencia"] * 120),
        "development": [
            {"heading": f"Bloco {index}", "body": long_body}
            for index in range(8)
        ],
        "conclusion": " ".join(["evidencia"] * 120),
        "cta": " ".join(["evidencia"] * 40),
    }

    class SequencedProvider:
        def __init__(self):
            self.prompts = []
            self.responses = [short, long]

        def generate(self, prompt):
            self.prompts.append(prompt)
            return AIResponse(
                text=json.dumps(
                    self.responses.pop(0),
                    ensure_ascii=False,
                )
            )

    provider = SequencedProvider()
    structure = generate_script_structure(
        idea_id,
        ai_provider=provider,
        target_duration_seconds=1200.0,
    )

    assert len(provider.prompts) == 2
    assert "pelo menos 2640 palavras" in provider.prompts[0]
    assert "pelo menos 8 blocos" in provider.prompts[0]
    assert (
        "EXPANSÃO EDITORIAL COMPLEMENTAR OBRIGATÓRIA"
        in provider.prompts[1]
    )
    assert len(structure["development"]) == 8


def test_longform_script_fails_closed_after_bounded_short_responses():
    import json

    from app.services.ai_provider import AIProviderError, AIResponse

    initialize_schema()
    idea_id = insert_idea(
        title="TESTE - longform insuficiente",
        description="Pauta factual curta.",
        status="approved",
        score=9.5,
    )
    payload = {
        "hook": "hook curto",
        "introduction": "intro curta",
        "development": [
            {"heading": f"Bloco {index}", "body": "conteudo curto"}
            for index in range(8)
        ],
        "conclusion": "conclusao curta",
        "cta": "cta curta",
    }

    class AlwaysShortProvider:
        def __init__(self):
            self.prompts = []

        def generate(self, prompt):
            self.prompts.append(prompt)
            return AIResponse(
                text=json.dumps(payload, ensure_ascii=False)
            )

    provider = AlwaysShortProvider()
    with pytest.raises(
        AIProviderError,
        match="cannot sustain requested long-form duration",
    ):
        generate_script_structure(
            idea_id,
            ai_provider=provider,
            target_duration_seconds=1200.0,
        )
    assert len(provider.prompts) == 3

def test_longform_script_retries_once_after_invalid_json_format():
    import json

    from app.services.ai_provider import AIResponse

    initialize_schema()
    idea_id = insert_idea(
        title="TESTE - longform formato json",
        description="Pauta factual com material suficiente para análise detalhada.",
        status="approved",
        score=9.5,
    )
    long_body = " ".join(["evidencia"] * 335)
    valid_long = {
        "hook": " ".join(["evidencia"] * 80),
        "introduction": " ".join(["evidencia"] * 120),
        "development": [
            {"heading": f"Bloco {index}", "body": long_body}
            for index in range(8)
        ],
        "conclusion": " ".join(["evidencia"] * 120),
        "cta": " ".join(["evidencia"] * 40),
    }

    class MalformedThenValidProvider:
        def __init__(self):
            self.prompts = []
            self.calls = 0

        def generate(self, prompt):
            self.prompts.append(prompt)
            self.calls += 1
            if self.calls == 1:
                return AIResponse(text="não é json")
            return AIResponse(
                text=json.dumps(valid_long, ensure_ascii=False)
            )

    provider = MalformedThenValidProvider()
    structure = generate_script_structure(
        idea_id,
        ai_provider=provider,
        target_duration_seconds=1200.0,
    )

    assert provider.calls == 2
    assert (
        "CORREÇÃO OBRIGATÓRIA DE FORMATO JSON"
        in provider.prompts[1]
    )
    assert "Escape barras invertidas" in provider.prompts[1]
    assert len(structure["development"]) == 8


def test_invalid_json_still_fails_closed_after_bounded_format_retry():
    from app.services.ai_provider import AIProviderError, AIResponse

    initialize_schema()
    idea_id = insert_idea(
        title="TESTE - json inválido bounded",
        description="Descrição factual válida.",
        status="approved",
        score=9.0,
    )

    class AlwaysMalformedProvider:
        def __init__(self):
            self.prompts = []

        def generate(self, prompt):
            self.prompts.append(prompt)
            return AIResponse(text="não é json")

    provider = AlwaysMalformedProvider()
    with pytest.raises(AIProviderError, match="invalid JSON"):
        generate_script_structure(
            idea_id,
            ai_provider=provider,
            target_duration_seconds=1200.0,
        )

    assert len(provider.prompts) == 2
    assert (
        "CORREÇÃO OBRIGATÓRIA DE FORMATO JSON"
        in provider.prompts[1]
    )

def test_longform_parser_repairs_invalid_backslash_escape_without_retry():
    import json

    from app.services.ai_provider import AIResponse

    initialize_schema()
    idea_id = insert_idea(
        title="TESTE - invalid escape reparável",
        description="Pauta factual suficiente.",
        status="approved",
        score=9.5,
    )
    long_body = " ".join(["evidencia"] * 335)
    valid_long = {
        "hook": " ".join(["evidencia"] * 80),
        "introduction": " ".join(["evidencia"] * 120),
        "development": [
            {"heading": f"Bloco {index}", "body": long_body}
            for index in range(8)
        ],
        "conclusion": " ".join(["evidencia"] * 120),
        "cta": " ".join(["evidencia"] * 40),
    }
    malformed = json.dumps(valid_long, ensure_ascii=False).replace(
        "evidencia evidencia",
        "evidencia \\q evidencia",
        1,
    )

    class InvalidEscapeProvider:
        def __init__(self):
            self.prompts = []

        def generate(self, prompt):
            self.prompts.append(prompt)
            return AIResponse(text=malformed)

    provider = InvalidEscapeProvider()
    structure = generate_script_structure(
        idea_id,
        ai_provider=provider,
        target_duration_seconds=1200.0,
    )

    assert len(provider.prompts) == 1
    assert "\\q" in structure["hook"]


def test_malformed_json_retry_is_bounded_and_format_only():
    import json

    from app.services.ai_provider import AIResponse

    initialize_schema()
    idea_id = insert_idea(
        title="TESTE - malformed retry específico",
        description="Pauta factual suficiente.",
        status="approved",
        score=9.5,
    )
    long_body = " ".join(["evidencia"] * 335)
    valid_long = {
        "hook": " ".join(["evidencia"] * 80),
        "introduction": " ".join(["evidencia"] * 120),
        "development": [
            {"heading": f"Bloco {index}", "body": long_body}
            for index in range(8)
        ],
        "conclusion": " ".join(["evidencia"] * 120),
        "cta": " ".join(["evidencia"] * 40),
    }

    class MalformedThenValidProvider:
        def __init__(self):
            self.prompts = []
            self.responses = ["não é json", json.dumps(valid_long, ensure_ascii=False)]

        def generate(self, prompt):
            self.prompts.append(prompt)
            return AIResponse(text=self.responses.pop(0))

    provider = MalformedThenValidProvider()
    structure = generate_script_structure(
        idea_id,
        ai_provider=provider,
        target_duration_seconds=1200.0,
    )

    assert len(provider.prompts) == 2
    assert "CORREÇÃO OBRIGATÓRIA DE FORMATO JSON" in provider.prompts[1]
    assert len(structure["development"]) == 8


def test_semantic_validation_failure_does_not_use_json_format_retry():
    from app.services.ai_provider import AIProviderError, AIResponse

    initialize_schema()
    idea_id = insert_idea(
        title="TESTE - JSON semanticamente inválido",
        description="Descrição válida.",
        status="approved",
        score=9.0,
    )

    class SemanticInvalidProvider:
        def __init__(self):
            self.prompts = []

        def generate(self, prompt):
            self.prompts.append(prompt)
            return AIResponse(
                text='{"hook":"x","introduction":"y","development":[],"conclusion":"z","cta":"w"}'
            )

    provider = SemanticInvalidProvider()
    with pytest.raises(AIProviderError, match="development"):
        generate_script_structure(idea_id, ai_provider=provider)
    assert len(provider.prompts) == 1

def test_longform_composes_distinct_bounded_passes_without_padding():
    import json

    from app.services.ai_provider import AIResponse

    initialize_schema()
    idea_id = insert_idea(
        title="TESTE - longform complementar",
        description="Pauta factual com várias evidências verificadas.",
        status="approved",
        score=9.5,
    )

    def structure(prefix, words_per_block):
        body = " ".join(
            f"{prefix}{index}" for index in range(words_per_block)
        )
        return {
            "hook": " ".join(["evidencia"] * 50),
            "introduction": " ".join(["contexto"] * 80),
            "development": [
                {
                    "heading": f"{prefix} Bloco {block}",
                    "body": body,
                }
                for block in range(4)
            ],
            "conclusion": " ".join(["conclusao"] * 50),
            "cta": " ".join(["cta"] * 20),
        }

    first = structure("A", 330)
    second = structure("B", 330)

    class ComplementaryProvider:
        def __init__(self):
            self.prompts = []
            self.responses = [first, second]

        def generate(self, prompt):
            self.prompts.append(prompt)
            return AIResponse(
                text=json.dumps(
                    self.responses.pop(0),
                    ensure_ascii=False,
                )
            )

    provider = ComplementaryProvider()
    result = generate_script_structure(
        idea_id,
        ai_provider=provider,
        editorial_context={
            "verified_claims": [
                {
                    "statement": "fato verificado",
                    "source": "https://www.rockstargames.com/",
                }
            ]
        },
        target_duration_seconds=1200.0,
    )

    assert len(provider.prompts) == 2
    assert "EXPANSÃO EDITORIAL COMPLEMENTAR OBRIGATÓRIA" in provider.prompts[1]
    assert "NÃO reescreva nem parafraseie" in provider.prompts[1]
    assert "Planeje cada body de development" in provider.prompts[0]
    assert "claims verificadas" in provider.prompts[0]
    assert "novos blocos de development" in provider.prompts[1]
    assert "palavras úteis restantes sem filler" in provider.prompts[1]
    assert len(result["development"]) == 8
    assert sum(
        len(str(item.get("body") or "").split())
        for item in result["development"]
    ) >= 2640

def test_longform_story_first_sequences_are_evidence_bounded_and_internal_metadata_is_not_audience_copy():
    import json

    from app.services.ai_provider import AIResponse
    from app.services import script_generator_service as generator

    initialize_schema()
    idea_id = insert_idea(
        title="TESTE - story first evidence bounded",
        description="Como as evidências oficiais e verificadas mudam a leitura da pauta?",
        status="approved",
        score=9.5,
    )

    def structure(prefix, words_per_block):
        body = " ".join(f"{prefix}{index}" for index in range(words_per_block))
        return {
            "hook": " ".join(["abertura"] * 50),
            "introduction": " ".join(["contexto"] * 80),
            "development": [
                {"heading": "Lançamento e plataformas", "body": body},
                {"heading": "Jason e Lucia", "body": body},
                {"heading": "Vice City e Leonida", "body": body},
                {"heading": "Música e mundo", "body": body},
            ],
            "conclusion": " ".join(["conclusao"] * 50),
            "cta": " ".join(["cta"] * 20),
        }

    first = structure("base", 80)
    seq_a = structure("aprofundamentoA", 390)
    seq_b = structure("aprofundamentoB", 390)

    class SequenceProvider:
        def __init__(self):
            self.prompts = []
            self.responses = [first, seq_a, seq_b]

        def generate(self, prompt):
            self.prompts.append(prompt)
            return AIResponse(text=json.dumps(self.responses.pop(0), ensure_ascii=False))

    claims = [
        {
            "claim_id": "release",
            "statement": "GTA VI chega em 19 de novembro de 2026 para PlayStation 5 e Xbox Series X|S.",
            "source": "https://www.rockstargames.com/VI",
            "evidence_refs": ["artifact:release"],
            "fact_check_result": "SUPPORTED",
        },
        {
            "claim_id": "duo",
            "statement": "Jason e Lucia dependem um do outro após um golpe dar errado.",
            "source": "https://www.rockstargames.com/VI",
            "evidence_refs": ["artifact:duo"],
            "fact_check_result": "SUPPORTED",
        },
        {
            "claim_id": "leonida",
            "statement": "A história atravessa Vice City e o estado de Leonida.",
            "source": "https://www.rockstargames.com/VI",
            "evidence_refs": ["artifact:leonida"],
            "fact_check_result": "SUPPORTED",
        },
        {
            "claim_id": "album",
            "statement": "O álbum oficial de música possui 34 faixas originais ligadas à energia do mundo de GTA VI.",
            "source": "https://www.rockstargames.com/VI",
            "evidence_refs": ["artifact:album"],
            "fact_check_result": "SUPPORTED",
        },
    ]
    provider = SequenceProvider()
    result = generate_script_structure(
        idea_id,
        ai_provider=provider,
        editorial_context={"verified_claims": claims},
        target_duration_seconds=1200.0,
    )

    assert len(provider.prompts) == 3
    assert "EVIDENCE-BOUNDED EDITORIAL SEQUENCE BATCH" in provider.prompts[1]
    assert "claims SUPPORTED desta sequence" in provider.prompts[1]
    assert "EXPANSÃO EDITORIAL COMPLEMENTAR OBRIGATÓRIA" not in provider.prompts[1]
    internal = result["_internal_editorial_structure"]
    covered_sequence_ids = {
        sequence_id
        for batch in internal["editorial_sequence_batches_generated"]
        for sequence_id in batch["sequence_ids"]
    }
    supported_sequence_ids = {
        item["sequence_id"]
        for item in internal["video_plan"]["sequences"]
        if item["status"] == "SUPPORTED"
    }
    assert covered_sequence_ids == supported_sequence_ids
    assert len(internal["editorial_sequence_batches_generated"]) == 2
    assert internal["video_plan"]["schema"] == "video-plan/v1"
    assert internal["story_assembly"]["schema"] == "story-assembly/v1"
    assert len(internal["video_plan"]["sequences"]) == 4
    assert internal["global_editorial_qa"]["TOTAL_SUPPORTED_DURATION"] == "PASS"
    assert internal["global_editorial_qa"]["content_supported_duration_minutes"] == 27.576
    assert internal["sequence_evidence_gaps"]
    assert internal["blocking_sequence_evidence_gaps"] == []
    assert internal["global_editorial_qa"]["EVIDENCE_COVERAGE"] == "PASS"
    assert internal["global_editorial_qa"]["ARTIFICIAL_PADDING"] == "OFF"
    audience = generator._structure_to_content(result)
    assert "sequence-001" not in audience
    assert "EVIDENCE-BOUNDED" not in audience
    assert "artifact:release" not in audience


def test_story_assembly_marks_duration_undercoverage_as_typed_sequence_evidence_gap():
    import json

    from app.services.ai_provider import AIProviderError, AIResponse

    initialize_schema()
    idea_id = insert_idea(
        title="TESTE - gap por duração suportada",
        description="Quais evidências sustentam cada parte da pauta?",
        status="approved",
        score=9.5,
    )

    def structure(prefix, words_per_block):
        body = " ".join(
            f"{prefix}{index}" for index in range(words_per_block)
        )
        return {
            "hook": " ".join(["abertura"] * 30),
            "introduction": " ".join(["contexto"] * 40),
            "development": [
                {"heading": "Lançamento", "body": body},
                {"heading": "Protagonistas", "body": body},
                {"heading": "Leonida", "body": body},
                {"heading": "Mundo", "body": body},
            ],
            "conclusion": " ".join(["conclusao"] * 30),
            "cta": " ".join(["cta"] * 10),
        }

    class ShortSequenceProvider:
        def __init__(self):
            self.prompts = []
            self.responses = [
                structure("base", 60),
                structure("curtoA", 25),
                structure("curtoB", 25),
            ]

        def generate(self, prompt):
            self.prompts.append(prompt)
            return AIResponse(
                text=json.dumps(
                    self.responses.pop(0),
                    ensure_ascii=False,
                )
            )

    claims = [
        {
            "claim_id": f"claim-{index}",
            "statement": statement,
            "source": "https://www.rockstargames.com/VI",
            "evidence_refs": [f"artifact:claim-{index}"],
            "fact_check_result": "SUPPORTED",
        }
        for index, statement in enumerate(
            (
                "GTA VI tem lançamento confirmado para consoles atuais.",
                "Jason e Lucia são protagonistas ligados pela história.",
                "Vice City integra o estado de Leonida.",
                "O mundo oficial apresenta diferentes regiões e atividades.",
            ),
            start=1,
        )
    ]
    provider = ShortSequenceProvider()

    with pytest.raises(
        AIProviderError,
        match="cannot sustain requested long-form duration",
    ) as captured:
        generate_script_structure(
            idea_id,
            ai_provider=provider,
            editorial_context={"verified_claims": claims},
            target_duration_seconds=1200.0,
        )

    evidence = getattr(captured.value, "failure_evidence", {})
    assert evidence["schema"] == "EditorialEvidenceGapFailure/v1"
    assert evidence["sequence_evidence_gaps"]
    assert (
        evidence["global_editorial_qa"]["EVIDENCE_COVERAGE"]
        == "GAPS_PRESENT"
    )
    assert any(
        float(item["estimated_missing_supported_duration"]) > 0.0
        for item in evidence["sequence_evidence_gaps"]
    )
    assert all(
        batch["actual_added_supported_duration"]
        < batch["expansion_target_duration"]
        for batch in evidence["editorial_sequence_batches_generated"]
    )


def test_story_plan_marks_uncovered_beat_as_sequence_evidence_gap_without_padding():
    from app.services import script_generator_service as generator

    initial = {
        "hook": "abertura",
        "introduction": "introducao",
        "development": [
            {"heading": "Lançamento", "body": "Data e plataformas confirmadas."},
            {"heading": "Economia interna", "body": "Pergunta editorial ainda sem base factual."},
            {"heading": "Protagonistas", "body": "Jason e Lucia conduzem a história."},
        ],
        "conclusion": "conclusao",
        "cta": "cta",
    }
    plan, gaps = generator._build_longform_video_plan(
        title="Pauta",
        description="O que as evidências realmente sustentam?",
        initial_structure=initial,
        editorial_context={
            "verified_claims": [
                {"statement": "A data de lançamento é 19 de novembro de 2026.", "source": "https://www.rockstargames.com/VI"},
                {"statement": "Jason e Lucia são os protagonistas.", "source": "https://www.rockstargames.com/VI"},
            ]
        },
        target_duration_seconds=1200.0,
    )

    assert plan["schema"] == "video-plan/v1"
    assert all("target_duration" in item for item in plan["sequences"])
    assert all("evidence_refs" in item for item in plan["sequences"])
    assert gaps
    assert gaps[0]["estimated_missing_supported_duration"] >= 0.0
