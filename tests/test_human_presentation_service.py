from __future__ import annotations

from copy import deepcopy
import json

from app.database.harness_authorization_repository import get_harness_authorization
from app.database.memory_event_repository import count_memory_events
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.human_presentation_service import (
    ACTION_FIRST,
    MACHINE_READABLE,
    PRESENTATION_CAPABILITY_ID,
    TECHNICAL_FULL,
    UPSTREAM_COMMIT,
    present_canonical_result_under_harness,
    render_human_presentation,
)


def test_action_first_presentation_skill_is_registered_without_authority():
    record = GLOBAL_CAPABILITY_REGISTRY.get(PRESENTATION_CAPABILITY_ID)
    assert record is not None
    assert record.capability_type == "PRESENTATION"
    assert record.domain == "human-presentation"
    assert record.allowed_actions == ("DECISION",)
    assert record.skill_id == PRESENTATION_CAPABILITY_ID
    assert record.instruction_path == ".dsh/skills/human-presentation-action-first/SKILL.md"
    assert record.side_effects == ()
    assert record.authority == "NONE"
    assert record.memory_write == "FORBIDDEN"
    assert record.routing_authority == "NONE"
    assert record.editorial_authority == "NONE"
    assert record.publication_authority == "NONE"
    assert record.fallback_eligibility is False
    assert "no-authority" in record.policy_tags
    assert "publication authority" in record.security_boundary
    assert "write memory" in record.security_boundary
    assert UPSTREAM_COMMIT in record.implementation


def test_action_first_does_not_mutate_canonical_result_or_nested_research_artifacts():
    canonical = {
        "status": "COMPLETED",
        "success": True,
        "answer": "A fonte foi verificada com evidência suficiente.",
        "source_intelligence": {
            "SOURCE_CONTENT_RESOLVED": "PASS",
            "claims": [{"verification_status": "VERIFIED", "text": "claim"}],
            "research_dossier": {"mission_id": "research-1", "evidence": ["a", "b"]},
            "claim_ledger": [{"claim_id": "claim-1", "fact_check_result": "SUPPORTED"}],
            "editorial_signal": {"harness_decision": "STORE_FOR_FUTURE"},
        },
    }
    before = deepcopy(canonical)
    result = render_human_presentation(
        canonical,
        surface="telegram",
        mode=ACTION_FIRST,
    )
    assert canonical == before
    assert result.canonical_unchanged is True
    assert result.mode == ACTION_FIRST
    assert "✅ Fonte analisada" in result.text
    assert "Ação do Harness: STORE_FOR_FUTURE" in result.text
    assert "Digite /evidence" in result.text
    assert canonical["source_intelligence"]["research_dossier"] == before["source_intelligence"]["research_dossier"]
    assert canonical["source_intelligence"]["claim_ledger"] == before["source_intelligence"]["claim_ledger"]


def test_insufficient_evidence_never_becomes_pass():
    canonical = {
        "answer": "Não há evidência independente suficiente para confirmar a alegação.",
        "source_intelligence": {
            "SOURCE_CONTENT_RESOLVED": "PASS",
            "claims": [{"verification_status": "INSUFFICIENT_EVIDENCE"}],
            "editorial_signal": {"harness_decision": "REJECT_LOW_EVIDENCE"},
        },
    }
    result = render_human_presentation(canonical, surface="telegram", mode=ACTION_FIRST)
    assert "⚠️ Evidência insuficiente" in result.text
    assert "Verificação: INSUFFICIENT_EVIDENCE" in result.text
    assert "Ação do Harness: REJECT_LOW_EVIDENCE" in result.text
    assert "Uso editorial: NÃO" in result.text
    assert "VERIFIED" not in result.text


def test_source_resolution_failure_remains_explicit_and_never_looks_successful():
    canonical = {
        "answer": "O conteúdo original da URL não pôde ser recuperado.",
        "source_intelligence": {
            "SOURCE_CONTENT_RESOLVED": "FAIL",
            "claims": [],
            "editorial_signal": {"harness_decision": "REJECT_LOW_EVIDENCE"},
        },
    }
    result = render_human_presentation(canonical, surface="telegram", mode=ACTION_FIRST)
    assert result.text.startswith("❌ Falha ao resolver a fonte")
    assert "Ação do Harness: REJECT_LOW_EVIDENCE" in result.text
    assert "Uso editorial: NÃO" in result.text
    assert "✅ Fonte analisada" not in result.text


def test_fail_remains_visible_and_only_observed_cause_is_shown():
    canonical = {
        "status": "FAILED",
        "success": False,
        "error": {"code": "upstream_http_403", "message": "HTTP 403 Forbidden"},
        "answer": "Tente novamente pelo executor governado disponível.",
    }
    result = render_human_presentation(canonical, surface="telegram", mode=ACTION_FIRST)
    assert result.text.startswith("❌ FAILED")
    assert "Causa observada: HTTP 403 Forbidden" in result.text
    assert "Ação: Tente novamente" in result.text


def test_action_first_never_hides_policy_violation_or_material_warning():
    canonical = {
        "status": "COMPLETED",
        "answer": "A operação terminou com restrições.",
        "policy_violations": [
            {"code": "PUBLICATION_GATE_DENIED", "message": "Publicação não autorizada."}
        ],
        "warnings": ["Resultado parcial; revisão humana necessária."],
    }
    result = render_human_presentation(
        canonical,
        surface="telegram",
        mode=ACTION_FIRST,
    )
    assert "Policy violation: Publicação não autorizada." in result.text
    assert "Aviso: Resultado parcial; revisão humana necessária." in result.text
    assert result.canonical_unchanged is True

def test_machine_readable_and_technical_full_are_lossless_projections():
    canonical = {
        "status": "COMPLETED",
        "answer": "ok",
        "ResearchDossier": {"items": [{"id": 1, "text": "full"}]},
        "ClaimLedger": [{"id": "c1", "status": "INSUFFICIENT_EVIDENCE"}],
        "FactCheckResult": {"verdict": "INSUFFICIENT_EVIDENCE"},
    }
    machine = render_human_presentation(
        canonical, surface="artifact", mode=MACHINE_READABLE
    )
    technical = render_human_presentation(
        canonical, surface="telegram", mode=TECHNICAL_FULL
    )
    assert json.loads(machine.text) == canonical
    assert json.loads(technical.text) == canonical
    assert machine.canonical_sha256 == technical.canonical_sha256
    assert machine.canonical_unchanged is True
    assert technical.canonical_unchanged is True


def test_harness_subordinated_presentation_has_no_memory_routing_or_publication_authority():
    canonical = {"status": "COMPLETED", "answer": "TESTE_OK"}
    before_memory = count_memory_events()
    result = present_canonical_result_under_harness(
        canonical,
        surface="telegram",
        lineage={"telegram_input_id": 1234},
    )
    after_memory = count_memory_events()

    assert result["text"] == "TESTE_OK"
    assert result["mode"] == ACTION_FIRST
    assert result["authority"] == "deepseek_harness"
    assert result["canonical_unchanged"] is True
    assert result["no_memory_authority"] is True
    assert result["no_routing_authority"] is True
    assert result["no_publication_authority"] is True
    assert after_memory == before_memory

    auth = get_harness_authorization(result["authorization_id"])
    assert auth is not None
    assert auth["status"] == "consumed"
    assert auth["subject"] == f"capability:{PRESENTATION_CAPABILITY_ID}"
    assert auth["authorized_action"] == "DECISION"
    assert auth["lineage"]["telegram_input_id"] == 1234
    assert auth["lineage"]["authority_scope"] == "presentation_only"
    assert auth["lineage"]["memory_write"] is False
    assert auth["lineage"]["routing_authority"] is False
    assert auth["lineage"]["publication_authority"] is False


def test_priority_human_surfaces_default_to_action_first():
    canonical = {"status": "COMPLETED", "answer": "AÇÃO_PRIMEIRO"}
    for surface in ("telegram", "termux", "work", "codex", "admin"):
        result = render_human_presentation(canonical, surface=surface)
        assert result.mode == ACTION_FIRST
        assert result.text == "AÇÃO_PRIMEIRO"


def test_action_first_metrics_measure_noise_reduction_without_storing_new_truth():
    canonical = {
        "status": "COMPLETED",
        "answer": "Fonte analisada com ressalvas.",
        "routing_id": "route-secret-ish-internal",
        "authorization_id": "auth-internal",
        "memory_id": "memory-internal",
        "warnings": ["Revisão humana necessária."],
        "source_intelligence": {
            "SOURCE_CONTENT_RESOLVED": "PASS",
            "claims": [{"verification_status": "INSUFFICIENT_EVIDENCE"}],
            "editorial_signal": {"harness_decision": "REJECT_LOW_EVIDENCE"},
        },
    }
    result = render_human_presentation(canonical, surface="telegram")
    assert result.canonical_lines > result.presented_lines
    assert result.canonical_internal_id_mentions >= 3
    assert result.presented_internal_id_mentions == 0
    assert result.conclusion_present is True
    assert result.next_action_present is True
    assert result.material_warnings_preserved is True
    assert result.evidence_access_present is True
    assert "route-secret-ish-internal" not in result.text
    assert "auth-internal" not in result.text
    assert "memory-internal" not in result.text


def test_artifact_surface_defaults_to_machine_readable_passthrough():
    canonical = {
        "status": "COMPLETED",
        "ResearchDossier": {"full": [1, 2, 3]},
        "ClaimLedger": [{"claim": "x", "status": "VERIFIED"}],
    }
    result = render_human_presentation(canonical, surface="artifact")
    assert result.mode == MACHINE_READABLE
    assert json.loads(result.text) == canonical
