"""Identity calibration dedup guard (A+C), RED->GREEN.

A: dedupe by sha256 before every identity calibration; effective floor =
   max(recorded, recalculated-with-duplicates, recalculated-deduped); status is
   PENDING_OWNER_APPROVAL (nothing recorded as owner-approved).
C: duplicate sha256 rejected at index load (materialization), >= 12 unique
   clips required, segments of one source clip are one calibration sample.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from app.services import owner_voice_identity_calibration_guard as G
from app.services.owner_voice_speaker_identity_service import (
    calibrate_owner_identity_profile,
    calibrate_owner_window_consistency,
    calibrate_segment_identity_threshold,
    cosine_similarity,
    evaluate_clone_identity_gate,
)

ROOT = Path(__file__).resolve().parents[1]


def _clips(n=14, dim=16, spread=0.25, seed=7):
    rng = np.random.default_rng(seed)
    base = rng.standard_normal(dim)
    emb = {str(40 + i): (base + spread * rng.standard_normal(dim)).tolist() for i in range(n)}
    sha = {k: hashlib.sha256(k.encode()).hexdigest() for k in emb}
    return emb, sha


def test_recorded_floors_are_the_last_calibrated_values_and_pending():
    r = G.RECORDED_IDENTITY_FLOORS
    assert r["clone_centroid_min_similarity"] == pytest.approx(0.8685941796030944)
    assert r["clone_reference_min_similarity"] == pytest.approx(0.7931407403048752)
    assert r["window_consistency_min_similarity"] == pytest.approx(0.593494)
    assert G.MIN_UNIQUE_CALIBRATION_CLIPS == 12
    assert G.GUARD_STATUS == "RECALCULATED_DEDUP_PENDING_OWNER_APPROVAL"
    assert G.OWNER_APPROVED_RECALCULATED_FLOORS is False


def test_exact_duplicates_and_same_source_segments_are_one_sample():
    emb, sha = _clips(3)
    emb["61"] = list(emb["40"]); sha["61"] = sha["40"]          # re-sent copy
    emb["41s00"] = emb["41"]; emb["41s01"] = emb["41"]          # segments of 41
    grouped, members = G.group_calibration_samples(emb, sha_by_id=sha, source_by_id={"41s00": "41", "41s01": "41"})
    assert sorted(grouped) == ["40", "41", "42"]
    assert members["40"] == ["40", "61"] and members["41"] == ["41", "41s00", "41s01"]


def test_fewer_than_12_unique_clips_fails_closed_even_with_many_duplicates():
    emb, sha = _clips(11)
    for k in list(emb):
        for j in range(4):
            emb[f"{k}d{j}"] = emb[k]; sha[f"{k}d{j}"] = sha[k]
    assert len(emb) == 55
    with pytest.raises(ValueError, match="OWNER_IDENTITY_CALIBRATION_REQUIRES_12_UNIQUE_CLIPS"):
        G.calibrate_guarded_identity_profile(emb, sha_by_id=sha)


def test_effective_floor_is_max_of_recorded_legacy_and_dedup_and_pending():
    emb, sha = _clips(14)
    mult = {k: (5 if i < 9 else 1) for i, k in enumerate(sorted(emb))}
    prof = G.calibrate_guarded_identity_profile(emb, sha_by_id=sha, multiplicity_by_id=mult)
    guard = prof["identity_calibration_guard"]
    dedup = calibrate_owner_identity_profile(emb)
    legacy_emb = {f"{k}#{j}": v for k, v in emb.items() for j in range(mult[k])}
    legacy = calibrate_owner_identity_profile(legacy_emb)
    for key in ("clone_centroid_min_similarity", "clone_reference_min_similarity"):
        expect = max(G.RECORDED_IDENTITY_FLOORS[key], dedup[key], legacy[key])
        assert prof[key] == pytest.approx(expect)
        assert prof[key] >= G.RECORDED_IDENTITY_FLOORS[key]
        assert guard["recalculated_dedup"][key] == pytest.approx(dedup[key], abs=1e-6)
        assert guard["recalculated_with_duplicates"][key] == pytest.approx(legacy[key], abs=1e-6)
    assert guard["status"] == "RECALCULATED_DEDUP_PENDING_OWNER_APPROVAL"
    assert guard["owner_approved"] is False
    assert guard["unique_clip_count"] == 14 and guard["duplicate_sample_count"] == 36
    assert guard["rule"] == "EFFECTIVE=MAX(RECORDED,RECALCULATED_WITH_DUPLICATES,RECALCULATED_DEDUP)"
    json.dumps(guard)  # public-safe scalars only
    assert "centroid" not in guard


def test_dedup_never_admits_a_clip_that_was_an_outlier_before():
    emb, sha = _clips(14)
    rng = np.random.default_rng(3)
    emb["99"] = rng.standard_normal(16).tolist(); sha["99"] = "f" * 64
    mult = {k: 1 for k in emb}
    legacy = calibrate_owner_identity_profile(emb)
    prof = G.calibrate_guarded_identity_profile(emb, sha_by_id=sha, multiplicity_by_id=mult)
    assert set(prof["inlier_ids"]) <= set(legacy["inlier_ids"])
    assert "99" not in prof["inlier_ids"]


def test_whole_audio_gate_requires_both_dedup_and_legacy_centroid():
    emb, sha = _clips(14)
    mult = {k: (5 if i < 9 else 1) for i, k in enumerate(sorted(emb))}
    prof = G.calibrate_guarded_identity_profile(emb, sha_by_id=sha, multiplicity_by_id=mult)
    assert "guard_legacy_centroid" in prof
    c = np.array(prof["centroid"])
    res = evaluate_clone_identity_gate(prof, clone_embedding=c.tolist(), canonical_embedding=c.tolist())
    assert "similarity_to_legacy_centroid" in res
    # Force the legacy centroid far away: dedup pass alone must not pass the gate.
    prof2 = dict(prof); prof2["guard_legacy_centroid"] = (-c).tolist()
    res2 = evaluate_clone_identity_gate(prof2, clone_embedding=c.tolist(), canonical_embedding=c.tolist())
    assert res2["passed"] is False and "LEGACY_CENTROID" in res2["guard_fail_reasons"]


def test_window_consistency_guard_groups_sources_and_never_lowers_recorded():
    scores = {"40": [0.5, 0.52, 0.55], "41": [0.6, 0.62, 0.7], "42": [0.58, 0.6, 0.61],
              "41s00": [0.1, 0.1, 0.1], "41s01": [0.1, 0.1, 0.1]}
    sha = {k: hashlib.sha256(k.encode()).hexdigest() for k in ("40", "41", "42")}
    cal = G.calibrate_guarded_window_consistency(scores, sha_by_id=sha, source_by_id={"41s00": "41", "41s01": "41"})
    assert cal["reference_count"] == 3
    assert cal["min_similarity"] >= G.RECORDED_IDENTITY_FLOORS["window_consistency_min_similarity"]
    assert cal["identity_calibration_guard"]["owner_approved"] is False
    raw = calibrate_owner_window_consistency({k: scores[k] for k in ("40", "41", "42")})
    assert cal["min_similarity"] == pytest.approx(max(0.593494, raw["min_similarity"]))


def test_segment_threshold_guard_weights_each_source_clip_once():
    by_clip = {"40": [0.9] * 40, "41": [0.6] * 4, "42": [0.62] * 4, "43": [0.64] * 4}
    flat = [v for vs in by_clip.values() for v in vs]
    base = calibrate_segment_identity_threshold(flat, window_seconds=6.0)
    cal = G.calibrate_guarded_segment_identity_threshold(by_clip, window_seconds=6.0)
    grouped = cal["identity_calibration_guard"]["grouped_centroid_min_similarity"]
    assert grouped == pytest.approx(G.weighted_group_quantile(by_clip, 0.10))
    assert cal["centroid_min_similarity"] == pytest.approx(max(base["centroid_min_similarity"], grouped))
    assert cal["centroid_min_similarity"] >= base["centroid_min_similarity"]


def _index(refs):
    base = {"schema": "OwnerTelegramVoiceReferenceIndex/v1", "voice_identity_id": "BR_OWNER_V1",
            "source": "AUTHORIZED_TELEGRAM_OWNER", "reference_count": len(refs), "references": refs}
    rendered = json.dumps(base, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {**base, "index_sha256": hashlib.sha256(rendered).hexdigest()}


def _ref(i, uid, msg):
    return {"telegram_input_id": i, "telegram_message_id": msg, "telegram_update_id": 2000 + i,
            "telegram_user_id": 77, "telegram_chat_id": -100, "input_kind": "voice",
            "telegram_file_id": f"fid-{i}", "telegram_file_unique_id": uid,
            "duration_seconds": 10.0, "mime_type": "audio/ogg", "remote_verified": True}


def test_materialization_rejects_duplicate_sha256_and_file_unique_id(tmp_path):
    from app.services.owner_voice_private_materialization_service import materialize_telegram_owner_references
    refs = [_ref(1, "u1", 101), _ref(2, "u2", 102), _ref(3, "u1", 103), _ref(4, "u4", 104)]
    content = {"fid-1": b"same-audio", "fid-2": b"other", "fid-4": b"same-audio"}
    calls = []
    def api(token, method, payload):
        assert method == "getFile"; calls.append(payload["file_id"])
        return {"file_path": payload["file_id"] + ".oga"}
    def dl(token, file_path, dest):
        dest.write_bytes(content[file_path[:-4]])
    (tmp_path / "repo").mkdir()
    out = materialize_telegram_owner_references(
        _index(refs), private_root=tmp_path / "p", repository_root=tmp_path / "repo",
        telegram_bot_token="t", api_call=api, downloader=dl)
    assert [r["telegram_input_id"] for r in out["references"]] == [1, 2]
    assert "fid-3" not in calls  # same Telegram file: never fetched
    rej = {r["telegram_input_id"]: r for r in out["duplicate_references_rejected"]}
    assert rej[3]["duplicate_of_input_id"] == 1 and rej[3]["reason"] == "TELEGRAM_FILE_UNIQUE_ID"
    assert rej[4]["duplicate_of_input_id"] == 1 and rej[4]["reason"] == "SHA256_EXACT"
    assert out["public_evidence"]["duplicate_rejected_count"] == 2
    assert len(list((tmp_path / "p").iterdir())) == 2
    assert G.multiplicity_from_materialization(out) == {"1": 3, "2": 1}


def test_scripts_use_guarded_calibration_everywhere():
    for rel in ("scripts/owner_voice_single_human_clone.py", "scripts/owner_voice_reference_asr_survey.py",
                "scripts/owner_voice_reference_segment_survey.py", "scripts/owner_voice_qwen3_tts_finetune_dataset.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "calibrate_guarded_identity_profile(" in src, rel
        assert "calibrate_owner_identity_profile(embeddings" not in src, rel
        assert "calibrate_owner_window_consistency(" not in src, rel
    clone = (ROOT / "scripts/owner_voice_single_human_clone.py").read_text(encoding="utf-8")
    assert "calibrate_guarded_segment_identity_threshold(" in clone
    assert "OWNER_IDENTITY_CALIBRATION_GUARD=" in clone


def test_sanitized_profile_never_exposes_any_centroid_embedding():
    from app.services.owner_voice_speaker_identity_service import sanitized_profile
    emb, sha = _clips(14)
    mult = {k: 2 for k in emb}
    prof = G.calibrate_guarded_identity_profile(emb, sha_by_id=sha, multiplicity_by_id=mult)
    safe = sanitized_profile(prof)
    assert "centroid" not in safe and "guard_legacy_centroid" not in safe
    assert safe["identity_calibration_guard"]["owner_approved"] is False
