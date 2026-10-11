"""Identity-anchor selection must rank by owner fidelity, not clip duration."""
from __future__ import annotations

import numpy as np
import pytest

from app.services.owner_voice_speaker_identity_service import (
    rank_identity_anchor_candidates,
    select_identity_prompt_references,
)
from app.services.owner_voice_serial_generation_v11 import (
    CANDIDATE_A_SAMPLING,
    CANDIDATE_A_BASE_SEED,
    generate_one_private_audition,
)


def _profile(sims):
    return {
        "inlier_ids":list(sims),
        "reference_similarity_to_centroid":dict(sims),
        "clone_centroid_min_similarity":0.8686,
    }


def _row(rid,duration,**extra):
    row={"reference_id":rid,"duration_seconds":duration,"snr_db":30.0,
         "sha256":rid*8,"ptbr_probability":0.97,"speech_ratio":0.8}
    row.update(extra)
    return row


def test_high_fidelity_short_clip_outranks_in_band_borderline_clip():
    profile=_profile({"a":0.97,"b":0.869})
    ranked=rank_identity_anchor_candidates([_row("b",12.0),_row("a",9.5)],profile)
    assert [r["reference_id"] for r in ranked]==["a","b"]


def test_duration_only_breaks_exact_similarity_ties():
    profile=_profile({"a":0.95,"b":0.95})
    ranked=rank_identity_anchor_candidates([_row("a",25.0),_row("b",14.0)],profile)
    assert [r["reference_id"] for r in ranked]==["b","a"]


def test_non_inliers_and_below_floor_are_excluded():
    profile=_profile({"a":0.95,"b":0.80})
    profile["inlier_ids"]=["b"]
    assert rank_identity_anchor_candidates([_row("a",12.0),_row("b",12.0)],profile)==[]


def test_compose_two_to_three_verified_refs_within_20_30s():
    profile=_profile({"a":0.96,"b":0.95,"c":0.94,"d":0.93})
    ranked=rank_identity_anchor_candidates(
        [_row("a",9.0),_row("b",8.0),_row("c",9.0),_row("d",9.0)],profile)
    chosen=select_identity_prompt_references(ranked,profile)
    assert [r["reference_id"] for r in chosen]==["a","b","c"]
    total=sum(r["duration_seconds"] for r in chosen)
    assert 20.0<=total<=30.0


def test_compose_rejects_unverified_ptbr_and_low_similarity():
    profile=_profile({"a":0.96,"b":0.95,"c":0.89})
    ranked=rank_identity_anchor_candidates(
        [_row("a",12.0),_row("b",12.0,ptbr_probability=0.5),_row("c",12.0)],profile)
    chosen=select_identity_prompt_references(ranked,profile)
    assert [r["reference_id"] for r in chosen]==["a"]


def test_compose_never_exceeds_30s():
    profile=_profile({"a":0.96,"b":0.95,"c":0.94})
    ranked=rank_identity_anchor_candidates(
        [_row("a",16.0),_row("b",16.0),_row("c",8.0)],profile)
    chosen=select_identity_prompt_references(ranked,profile)
    assert [r["reference_id"] for r in chosen]==["a","c"]


def test_candidate_a_sampling_and_fixed_seed_reach_every_generate_call(tmp_path):
    assert CANDIDATE_A_SAMPLING=={
        "do_sample":True,"temperature":0.7,"top_p":0.9,"top_k":50,
        "subtalker_dosample":True,"subtalker_temperature":0.7,
        "subtalker_top_p":0.9,"subtalker_top_k":50,
    }
    assert CANDIDATE_A_BASE_SEED==424242
    calls=[];seeds=[]
    def generate(**kw):
        calls.append(kw)
        return [np.ones(4800,dtype=np.float32)*0.1],24000
    generate_one_private_audition(
        generate=generate,heartbeat=lambda fn,**kw:fn(**kw),
        segment_texts=["um","dois"],segment_languages=["Portuguese"]*2,
        segment_prompts=[object(),object()],workspace=tmp_path,
        sampling_kwargs=CANDIDATE_A_SAMPLING,seed_setter=seeds.append,
        base_seed=CANDIDATE_A_BASE_SEED,
    )
    assert seeds==[424242,424243]
    for c in calls:
        for k,v in CANDIDATE_A_SAMPLING.items():
            assert c[k]==v
