from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from app.services import reverse_engineering_fidelity_v5_service as fidelity
from app.services.reverse_engineering_media_service import ObservationError


def _files(tmp_path):
    ref = tmp_path / "owned.mp4"
    candidate = tmp_path / "candidate.mp4"
    ref.write_bytes(b"original")
    candidate.write_bytes(b"original but edited")
    return ref, candidate


def _probe():
    return {"duration_seconds": 2.0, "streams": [
        {"codec_type": "video", "width": 128, "height": 72,
         "avg_frame_rate": "10/1", "r_frame_rate": "10/1"},
        {"codec_type": "audio", "sample_rate": "16000", "channels": 1},
    ]}


def test_rights_and_identical_source_path_rejected_before_probing(tmp_path, monkeypatch):
    a, b = _files(tmp_path)
    monkeypatch.setattr(fidelity, "probe_media", lambda *_: pytest.fail("not authorized"))
    with pytest.raises(ObservationError, match="COPY_RIGHTS_NOT_ESTABLISHED"):
        fidelity.compare_reconstruction(a, b, rights="observation_only", candidate_rights="owned")
    with pytest.raises(ObservationError, match="IDENTICAL_SOURCE_PATH"):
        fidelity.compare_reconstruction(a, a, rights="owned", candidate_rights="owned")


@pytest.mark.parametrize("ratio,issue", [
    ({"avg_frame_rate": "30/1"}, "FRAME_RATE_MISMATCH"),
    ({"r_frame_rate": "30/1"}, "FRAME_RATE_MISMATCH"),
    ({"avg_frame_rate": "0/0"}, "FRAME_RATE_UNVERIFIED"),
])
def test_fps_inconsistency_blocks_false_precision(ratio, issue):
    row = dict(_probe()["streams"][0], **ratio)
    with pytest.raises(ObservationError, match=issue):
        fidelity._fps(row)


def test_wrong_dimensions_or_fps_rejected_without_processing(tmp_path, monkeypatch):
    a, b = _files(tmp_path)
    p = _probe()
    q = copy.deepcopy(p)
    q["streams"][0]["width"] = 1920
    monkeypatch.setattr(fidelity, "_call", lambda *_args, **kwargs: pytest.fail("should not decode"))
    with pytest.raises(ObservationError, match="RESOLUTION_MISMATCH"):
        fidelity._video(a, b, refprobe=p, canprobe=q, seconds=2)


def test_measured_video_metric_parser_requires_each_frame(tmp_path, monkeypatch):
    a, b = _files(tmp_path)
    p = _probe()
    class Result:
        def __init__(self, stdout):
            self.stdout = stdout
            self.stderr = ""
    def fake_call(args, **kw):
        graph = args[args.index("-filter_complex") + 1]
        assert "[candidate][reference]" in graph
        assert "setpts=PTS-STARTPTS" in graph
        if "psnr=stats_file=-" in graph:
            return Result("n:1 mse_avg:0.00 mse_y:0.00\nn:2 mse_avg:0.00 mse_y:0.00\n")
        return Result("n:1 Y:1.0 U:1.0 V:1.0 All:1.000000 (inf)\nn:2 Y:1.0 U:1.0 V:1.0 All:1.000000 (inf)\n")
    monkeypatch.setattr(fidelity, "_call", fake_call)
    v = fidelity._video(a, b, refprobe=p, canprobe=q_from(p), seconds=0.2)
    assert v["psnr_compared_frames"] == 2
    assert v["ssim_compared_frames"] == 2
    assert v["lossless_pixel_match"] is True
    assert v["mean_frame_ssim"] == 1.0


def q_from(p):
    return copy.deepcopy(p)


def test_audio_waveform_residual_catches_gain_change_even_if_corr_one(tmp_path, monkeypatch):
    a, b = _files(tmp_path)
    samples = np.sin(np.linspace(0, 100.0, 32_000, dtype=np.float64)) * 0.2
    monkeypatch.setattr(fidelity, "_pcm", lambda path, seconds: samples if path == a else samples * 0.5)
    report = fidelity._audio(a, b, refprobe=_probe(), canprobe=_probe(), seconds=2)
    assert report["status"] == "MEASURED"
    assert report["normalized_correlation"] == 1.0
    assert 0.499 < report["candidate_to_reference_rms_ratio"] < 0.501
    assert report["unadjusted_difference_rmse_linear"] > 0.01
    assert report["waveform_bit_equivalent_after_decode"] is False
    assert "identity" in report["limitations"].lower() or "speaker" in report["limitations"].lower()


def test_source_hashes_and_no_identity_claim(tmp_path, monkeypatch):
    a, b = _files(tmp_path)
    monkeypatch.setattr(fidelity, "probe_media", lambda *_: _probe())
    monkeypatch.setattr(fidelity, "_video", lambda *_a, **_kw: {
        "status": "MEASURED", "lossless_pixel_match": True,
    })
    monkeypatch.setattr(fidelity, "_audio", lambda *_a, **_kw: {
        "status": "MEASURED", "waveform_bit_equivalent_after_decode": False,
    })
    output = fidelity.compare_reconstruction(a, b, rights="owned", candidate_rights="licensed")
    assert output["quality_approved"] is False
    assert output["identity_verified"] is False
    assert output["publication_authorized"] is False
    assert output["full_duration_analyzed"] is True
    assert output["difference_classes"] == ["WAVEFORM_DIFFERENCE_REVIEW_TIMING_GAIN_AND_MIX"]
    assert len(output["evidence_sha256"]) == 64
    assert output["source"]["sha256"] != output["candidate"]["sha256"]


def test_audio_missing_is_not_fabricated(tmp_path):
    a, b = _files(tmp_path)
    empty = {"duration_seconds": 2.0, "streams": [{"codec_type": "video"}]}
    result = fidelity._audio(a, b, refprobe=empty, canprobe=empty, seconds=2)
    assert result["status"] == "NOT_APPLICABLE"


def test_invalid_window_and_duration_are_fail_closed(tmp_path, monkeypatch):
    a, b = _files(tmp_path)
    for v in [0, 12.1, -1, float("nan")]:
        with pytest.raises(ObservationError, match="FIDELITY_WINDOW_UNSUPPORTED"):
            fidelity.compare_reconstruction(a, b, rights="owned", candidate_rights="owned", window_seconds=v)
    bad = _probe()
    bad["duration_seconds"] = 0.2
    monkeypatch.setattr(fidelity, "probe_media", lambda *_: bad)
    with pytest.raises(ObservationError, match="INCOMPLETE_SOURCE_WINDOW"):
        fidelity.compare_reconstruction(a, b, rights="owned", candidate_rights="owned", window_seconds=2)



def test_audio_fft_detects_shift_but_does_not_adjust_original(tmp_path, monkeypatch):
    a, b = _files(tmp_path)
    rng = np.random.default_rng(2026)
    reference = rng.normal(size=32_000).astype("float64") * 0.1
    delayed = np.zeros_like(reference)
    delayed[320:] = reference[:-320]
    monkeypatch.setattr(fidelity, "_pcm", lambda path, seconds: reference if path == a else delayed)
    result = fidelity._audio(a, b, refprobe=_probe(), canprobe=_probe(), seconds=2)
    measurements = result["alignment_and_spectrum"]
    assert abs(measurements["candidate_minus_reference_lag_ms"] - 20.0) <= 0.063
    assert result["waveform_bit_equivalent_after_decode"] is False
    assert result["unadjusted_difference_rmse_linear"] > 0.05
    assert "UNVERIFIED" in measurements["lag_interpretation"]


def test_spectrum_reports_gain_change_not_fake_voice_quality(tmp_path, monkeypatch):
    a, b = _files(tmp_path)
    rng = np.random.default_rng(2027)
    samples = rng.normal(size=32_000) * 0.04
    monkeypatch.setattr(fidelity, "_pcm", lambda path, seconds: samples if path == a else samples / 2)
    result = fidelity._audio(a, b, refprobe=_probe(), canprobe=_probe(), seconds=2)
    spectral = result["alignment_and_spectrum"]
    for value in spectral["candidate_minus_reference_band_energy_db"].values():
        assert value is not None
        assert abs(value + 6.0206) < 0.01
    assert result["normalized_correlation"] == 1.0
    assert result["waveform_bit_equivalent_after_decode"] is False



def test_missing_track_on_one_side_is_rejected_instead_of_called_not_applicable(tmp_path):
    a,b = _files(tmp_path)
    p=_probe()
    audio_only={"duration_seconds":2.0,"streams":[p["streams"][1]]}
    video_only={"duration_seconds":2.0,"streams":[p["streams"][0]]}
    with pytest.raises(ObservationError,match="FIDELITY_VIDEO_STREAM_TOPOLOGY_MISMATCH"):
        fidelity._video(a,b,refprobe=p,canprobe=audio_only,seconds=2)
    with pytest.raises(ObservationError,match="FIDELITY_AUDIO_STREAM_TOPOLOGY_MISMATCH"):
        fidelity._audio(a,b,refprobe=p,canprobe=video_only,seconds=2)


def test_audio_channel_or_sample_rate_change_requires_explicit_conform(tmp_path):
    a,b = _files(tmp_path)
    original=_probe()
    candidate=_probe()
    candidate["streams"][1]["channels"]=2
    with pytest.raises(ObservationError,match="FIDELITY_AUDIO_CHANNEL_OR_SAMPLE_RATE_MISMATCH"):
        fidelity._audio(a,b,refprobe=original,canprobe=candidate,seconds=2)
    candidate=_probe()
    candidate["streams"][1]["sample_rate"]="44100"
    with pytest.raises(ObservationError,match="FIDELITY_AUDIO_CHANNEL_OR_SAMPLE_RATE_MISMATCH"):
        fidelity._audio(a,b,refprobe=original,canprobe=candidate,seconds=2)
