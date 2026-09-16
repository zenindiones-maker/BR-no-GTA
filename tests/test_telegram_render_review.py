from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from scripts.telegram_render_review_worker import _send_video, deliver_render_review


def _write_render_evidence(root: Path) -> Path:
    folder = root / "run001-video-a" / "20"
    folder.mkdir(parents=True)
    (folder / "4.mp4").write_bytes(b"rendered-video")
    (folder / "render-job.json").write_text(
        json.dumps(
            {
                "render_job_id": 20,
                "video_id": 4,
                "execution_id": "run001-video-a",
                "brand_assets": [
                    {"asset_id": 1, "asset_type": "intro"},
                    {"asset_id": 2, "asset_type": "watermark"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (folder / "render-qa.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "branding": {
                    "intro_duration_seconds": 10.005333,
                    "watermark_start_seconds": 10.005333,
                    "watermark_scale": 0.16,
                    "watermark_margin": {"x": 25, "y": 24},
                    "watermark_opacity": 0.78,
                },
            }
        ),
        encoding="utf-8",
    )
    return folder


def test_render_review_delivers_full_duration_proxy_and_persists_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    folder = _write_render_evidence(tmp_path / "output")
    proxy = tmp_path / "telegram-review.mp4"
    proxy.write_bytes(b"full-duration-proxy")
    sent: dict = {}
    proxy_request: dict = {}

    def fake_proxy(source, output_dir):
        proxy_request.update(source=source, output_dir=output_dir)
        return (
            proxy,
            {
                "duration_seconds": 1510.005333,
                "size_bytes": proxy.stat().st_size,
                "sha256": "proxy-sha",
            },
        )

    monkeypatch.setattr(
        "scripts.telegram_render_review_worker.build_review_proxy", fake_proxy
    )

    def fake_send(**kwargs):
        sent.update(kwargs)
        return {
            "message_id": 77,
            "video": {"file_id": "tg-file", "file_unique_id": "tg-unique"},
        }

    monkeypatch.setattr("scripts.telegram_render_review_worker._send_video", fake_send)

    result = deliver_render_review(
        artifact_root=tmp_path / "output",
        token="bot-token",
        review_chat_id="-100123",
        run_id="35110000000",
    )

    assert result["status"] == "DELIVERED"
    assert result["telegram_message_id"] == 77
    assert result["proxy"]["duration_seconds"] == 1510.005333
    assert result["asset_ids"] == [1, 2]
    assert "NÃO PUBLICAR" in sent["caption"]
    assert "intro=10.005333s" in sent["caption"]
    assert sent["video"] == proxy
    assert sent["chat_id"] == "-100123"
    assert not proxy_request["output_dir"].is_relative_to(tmp_path / "output")
    assert len(list((tmp_path / "output").rglob("*.mp4"))) == 1
    persisted = json.loads(
        (folder / "telegram-review.json").read_text(encoding="utf-8")
    )
    assert persisted == result


@pytest.mark.parametrize(
    ("token", "chat_id"),
    [("", "-100123"), ("bot-token", "")],
)
def test_render_review_requires_telegram_delivery_configuration(
    tmp_path: Path, token: str, chat_id: str
):
    _write_render_evidence(tmp_path / "output")
    with pytest.raises(RuntimeError):
        deliver_render_review(
            artifact_root=tmp_path / "output",
            token=token,
            review_chat_id=chat_id,
            run_id="35110000000",
        )


def test_render_review_refuses_non_passing_branding_qa(tmp_path: Path):
    folder = _write_render_evidence(tmp_path / "output")
    (folder / "render-qa.json").write_text(
        json.dumps({"status": "FAIL", "branding": {}}), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="QA must be PASS"):
        deliver_render_review(
            artifact_root=tmp_path / "output",
            token="bot-token",
            review_chat_id="-100123",
            run_id="35110000000",
        )


def test_render_review_refuses_swapped_official_asset_types(tmp_path: Path):
    folder = _write_render_evidence(tmp_path / "output")
    job_path = folder / "render-job.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job["brand_assets"] = [
        {"asset_id": 1, "asset_type": "watermark"},
        {"asset_id": 2, "asset_type": "intro"},
    ]
    job_path.write_text(json.dumps(job), encoding="utf-8")
    with pytest.raises(RuntimeError, match="official brand asset IDs"):
        deliver_render_review(
            artifact_root=tmp_path / "output",
            token="bot-token",
            review_chat_id="-100123",
            run_id="35110000000",
        )


def test_render_worker_requires_telegram_review_before_success_artifact():
    workflow = Path(".github/workflows/render-worker.yml").read_text(encoding="utf-8")
    apply_index = workflow.index("Apply governed intro and watermark")
    review_index = workflow.index("Deliver full-duration branded review to Telegram")
    artifact_index = workflow.index("Upload QA-passed render")
    assert apply_index < review_index < artifact_index
    assert "scripts/telegram_render_review_worker.py" in workflow
    assert "TELEGRAM_REVIEW_CHAT_ID" in workflow


def test_render_review_transport_error_does_not_retain_bot_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    video = tmp_path / "review.mp4"
    video.write_bytes(b"review")
    token = "secret-bot-token"

    def fail_post(*_args, **_kwargs):
        raise requests.RequestException(
            f"request failed at https://api.telegram.org/bot{token}/sendVideo"
        )

    monkeypatch.setattr("scripts.telegram_render_review_worker.requests.post", fail_post)
    with pytest.raises(RuntimeError) as caught:
        _send_video(token=token, chat_id="-100123", video=video, caption="review")
    assert token not in str(caught.value)
    assert caught.value.__cause__ is None
