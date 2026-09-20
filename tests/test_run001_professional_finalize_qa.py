from scripts.run001_professional_finalize_qa import spoken_branding_qa_pass, subtitles_qa_pass


def _job():
    return {
        "subtitles": {
            "enabled": False,
            "burned_subtitles": False,
            "open_captions": False,
            "transcript_overlay": False,
            "srt_burn_in": False,
        }
    }


def _edit_qa():
    return {
        "status": "PASS",
        "checks": {
            "subtitles_default_disabled": True,
            "burned_subtitles_disabled": True,
        },
    }


def _probe():
    return {
        "streams": [
            {"codec_type": "video", "closed_captions": 0},
            {"codec_type": "audio"},
        ]
    }


def test_subtitles_gate_accepts_persisted_edit_qa_when_checkpoint_omits_edit_plan():
    assert subtitles_qa_pass(job=_job(), edit_qa=_edit_qa(), probe=_probe(), edit_plan=None)


def test_subtitles_gate_still_rejects_burned_caption_tracks_when_edit_plan_is_present():
    assert not subtitles_qa_pass(
        job=_job(),
        edit_qa=_edit_qa(),
        probe=_probe(),
        edit_plan={"texts": [{"track": "CAPTIONS"}]},
    )


def test_subtitles_gate_rejects_missing_persisted_edit_proof():
    edit_qa=_edit_qa()
    edit_qa["checks"]["burned_subtitles_disabled"]=False
    assert not subtitles_qa_pass(job=_job(), edit_qa=edit_qa, probe=_probe(), edit_plan=None)


def test_subtitles_gate_rejects_subtitle_stream_or_closed_captions():
    probe=_probe()
    probe["streams"].append({"codec_type": "subtitle"})
    assert not subtitles_qa_pass(job=_job(), edit_qa=_edit_qa(), probe=probe, edit_plan=None)


def test_spoken_branding_gate_accepts_persisted_render_qa_when_manifest_is_omitted():
    render_qa={
        "status":"PASS",
        "checks":{
            "intro_present":True,
            "spoken_opening_after_intro":True,
            "voice_b_used":True,
            "opening_text_canonical":True,
            "closing_text_canonical":True,
            "brand_audio_cache_policy":True,
            "editorial_hook_preserved":True,
        },
    }
    no_padding={"job18_unchanged":True,"no_youtube_publish":True}
    assert spoken_branding_qa_pass(render_qa=render_qa,no_padding=no_padding,manifest=None)


def test_spoken_branding_gate_rejects_incomplete_persisted_render_qa():
    render_qa={
        "status":"PASS",
        "checks":{
            "intro_present":True,
            "spoken_opening_after_intro":True,
            "voice_b_used":False,
            "opening_text_canonical":True,
            "closing_text_canonical":True,
            "brand_audio_cache_policy":True,
            "editorial_hook_preserved":True,
        },
    }
    no_padding={"job18_unchanged":True,"no_youtube_publish":True}
    assert not spoken_branding_qa_pass(render_qa=render_qa,no_padding=no_padding,manifest=None)
