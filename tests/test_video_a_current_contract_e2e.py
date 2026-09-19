from pathlib import Path

from app.services.current_audio_contract_service import current_audio_contract


def test_current_audio_contract_hash_and_voice_are_pinned():
    contract=current_audio_contract()
    assert contract["OFFICIAL_VOICE"]=="Voice B"
    assert contract["VOICE_SHORT_NAME"]=="pt-BR-ThalitaMultilingualNeural"
    assert contract["APPROVED_G_SHA256"]=="9e2e7a2d9717f460dd45cf0d07e96a4596e4f61372c6d87028b8809a052c59ca"


def test_professional_worker_has_no_burned_brand_caption_track():
    source=Path("app/workers/professional_audiovisual_worker.py").read_text(encoding="utf-8")
    assert 'track="BRAND_CAPTIONS"' not in source
    assert "min_duration_seconds=max(1.0, duration * 0.98)" in source
    assert "max_duration_seconds=duration * 1.02" in source


def test_current_e2e_uses_artifact_handoff_for_job2():
    workflow=Path(".github/workflows/video-a-current-product-e2e.yml").read_text(encoding="utf-8")
    assert "Publish governed current Job2 handoff" in workflow
    assert "render-job-handoff/render-job.json" in workflow
    assert "dispatch-handoff" in workflow


def test_current_recovery_binds_proven_render_profile_v4():
    source=Path("scripts/video_a_current_contract_recovery.py").read_text(encoding="utf-8")
    assert 'candidate") != "vedit.longform.render-profile@v4"' in source
    assert '"version"] != "v4"' in source
    assert '"timeline_placement") != "timestamp"' in source
    assert '"compact_text_overlays") is not True' in source
    assert 'print("RENDER_PROFILE=v4")' in source


def test_no_padding_wpm_gate_is_strict_for_real_jobs_but_fixture_compatible():
    source=Path("scripts/run001_longform_no_padding_qa.py").read_text(encoding="utf-8")
    assert 'if isinstance(script_sections, list) and script_sections:' in source
    assert 'if not 90.0 <= observed_wpm <= 180.0:' in source
