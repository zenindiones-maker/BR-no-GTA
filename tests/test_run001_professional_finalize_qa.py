from scripts.run001_professional_finalize_qa import subtitles_qa_pass


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
