import os
import tempfile

from app.services.vedit_service import (
    VEditPolicy,
    build_brain_context,
    create_edit_plan,
)


fd, media_path = tempfile.mkstemp(suffix=".mp4")
os.close(fd)

try:
    with open(media_path, "wb") as f:
        f.write(b"VEDIT-REAL-MEDIA-TEST")

    production_plan = {
        "content_item_id": 101,
        "script_id": 202,
        "idea_id": 303,
        "objective": "informar",
        "format": "short",
        "estimated_duration_seconds": 20.0,

        "scenes": [
            {
                "order": 1,
                "segment_id": 1,
                "narrative_block": "intro",
                "narration": "Temos uma nova informação importante sobre GTA 6.",
                "file_path": media_path,
                "source_start_seconds": 0.0,
                "source_end_seconds": 4.0,
                "duration_seconds": 4.0,
                "visual_type": "title_card",
                "visual_description": "Cartela de abertura com identidade visual GTA 6 e destaque da informação principal.",
                "semantic_relevance": 0.95,
                "editorial_relevance": 0.96,
                "visual_quality": 0.90,
                "motion": 0.85,
                "audio_energy": 0.90,
                "narrative_fit": 0.98,
            },
            {
                "order": 2,
                "segment_id": 2,
                "narrative_block": "context",
                "narration": "Os detalhes foram identificados nas informações mais recentes.",
                "file_path": media_path,
                "source_start_seconds": 4.0,
                "source_end_seconds": 9.0,
                "duration_seconds": 5.0,
                "visual_type": "gameplay",
                "visual_description": "Gameplay de GTA 6 contextualizando a informação apresentada na narração.",
                "semantic_relevance": 0.92,
                "editorial_relevance": 0.90,
                "visual_quality": 0.88,
                "motion": 0.70,
                "audio_energy": 0.60,
                "narrative_fit": 0.94,
            },
            {
                "order": 3,
                "segment_id": 3,
                "narrative_block": "impact",
                "narration": "Isso pode mudar bastante o que esperamos do próximo anúncio.",
                "file_path": media_path,
                "source_start_seconds": 9.0,
                "source_end_seconds": 16.0,
                "duration_seconds": 7.0,
                "visual_type": "gameplay_with_graphics",
                "visual_description": "Gameplay de GTA 6 com elementos gráficos destacando o impacto da informação.",
                "semantic_relevance": 0.94,
                "editorial_relevance": 0.95,
                "visual_quality": 0.91,
                "motion": 0.94,
                "audio_energy": 0.90,
                "narrative_fit": 0.95,
            },
            {
                "order": 4,
                "segment_id": 4,
                "narrative_block": "conclusion",
                "narration": "Agora é acompanhar os próximos anúncios.",
                "file_path": media_path,
                "source_start_seconds": 16.0,
                "source_end_seconds": 20.0,
                "duration_seconds": 4.0,
                "visual_type": "summary_graphics",
                "visual_description": "Gráfico visual de resumo encerrando a narrativa e reforçando a informação principal.",
                "semantic_relevance": 0.85,
                "editorial_relevance": 0.88,
                "visual_quality": 0.84,
                "motion": 0.60,
                "audio_energy": 0.50,
                "narrative_fit": 0.90,
            },
        ],

        "audio_requirements": [],
        "visual_requirements": [],
    }

    brain = build_brain_context(
        action="EXECUTION",
        reason="teste real VEDIT",
        priority="HIGH",
        confidence=0.95,
    )

    plan = create_edit_plan(
        production_plan=production_plan,
        brain_decision=brain,
        policy=VEditPolicy(),
    )

    print("EDIT PLAN:", type(plan).__name__)
    print("duration:", plan.duration_seconds)
    print("tracks:", [t.name for t in plan.tracks])
    print("clips:", sum(len(t.clips) for t in plan.tracks))
    print("texts:", len(plan.texts))
    print("audio:", len(plan.audio))
    print("transitions:", len(plan.transitions))
    print("effects:", len(plan.effects))
    print("qa:", plan.qa)
    print("metadata keys:", sorted(plan.metadata.keys()))

    assert plan.tracks
    assert any(t.clips for t in plan.tracks)
    assert plan.texts
    assert plan.transitions
    assert plan.effects
    assert "scoring" in plan.metadata
    assert "editorial_decisions" in plan.metadata
    assert "timeline" in plan.metadata
    assert "qa_director" in plan.metadata

    print("===== VEDIT REAL INTEGRATION OK =====")

finally:
    os.unlink(media_path)
