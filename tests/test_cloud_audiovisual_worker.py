"""Worker contract tests. Synthetic fixtures are NOT RUN-001 evidence."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.edit_plan_service import EditQA
from app.workers.audiovisual_worker import (
    WorkerError, build_timeline, evaluate_probe, execute, resolve_asset, validate_job,
)


def job():
    return {
        "render_job_id": 1, "video_id": 2, "content_item_id": 3,
        "script_id": 4, "idea_id": 5, "brain_decision_id": "decision-test",
        "execution_id": "execution-test", "authorized_action": "EXECUTION",
        "estimated_duration_seconds": 40,
        "scenes": [{"segment_id": 6, "content_unit_id": 7}],
        "render": {"resolution": "1920x1080", "fps": 30, "container": "mp4", "video_codec": "h264", "audio_codec": "aac"},
        "edit_plan": {
            "version": "1", "content_item_id": 3, "script_id": 4,
            "title": "contract fixture", "objective": "test", "format": "video",
            "duration_seconds": 40,
            "tracks": [{"name": "V1", "kind": "video", "clips": [{
                "segment_id": 6, "media_path": "source.mp4", "track": "V1",
                "start_seconds": 0, "source_start_seconds": 2, "duration_seconds": 40,
            }]}],
        },
    }


class ContractTests(unittest.TestCase):
    def test_required_ids_and_edit_plan(self):
        for field in ("render_job_id", "video_id", "content_item_id", "script_id", "idea_id", "edit_plan", "scenes", "execution_id", "brain_decision_id"):
            data = job()
            del data[field]
            with self.subTest(field=field), self.assertRaises(WorkerError):
                validate_job(data)

    def test_invalid_authorization_and_lineage(self):
        data = job()
        data["authorized_action"] = "EDITORIAL"
        with self.assertRaises(WorkerError):
            validate_job(data)
        data = job()
        data["edit_plan"]["script_id"] = 999
        with self.assertRaises(WorkerError):
            validate_job(data)
        with patch.dict("os.environ", EXPECTED_EXECUTION_ID="other"), self.assertRaises(WorkerError):
            validate_job(job())

    def test_nonfinite_and_secrets(self):
        for value in (float("nan"), float("inf"), -1, True):
            data = job()
            data["estimated_duration_seconds"] = value
            with self.assertRaises(WorkerError):
                validate_job(data)
        data = job()
        data["edit_plan"]["metadata"] = {"access_token": "never archive"}
        with self.assertRaises(WorkerError):
            validate_job(data)

    def test_asset_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "source.mp4").write_bytes(b"fixture")
            self.assertEqual(resolve_asset("source.mp4", root), root / "source.mp4")
            for invalid in ("../source.mp4", "/etc/passwd", "missing.mp4"):
                with self.assertRaises(WorkerError):
                    resolve_asset(invalid, root)

    def test_qa_checks_audio_and_duration(self):
        probe = {"format": {"duration": "40", "format_name": "mov,mp4"}, "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}
        self.assertEqual(evaluate_probe(probe, 40, EditQA())["status"], "PASS")
        self.assertEqual(evaluate_probe(probe, 1500, EditQA())["status"], "FAIL")
        probe["streams"].pop()
        self.assertEqual(evaluate_probe(probe, 40, EditQA())["status"], "FAIL")
        for duration in ("nan", "inf", "0", "-1"):
            probe["format"]["duration"] = duration
            self.assertEqual(evaluate_probe(probe, 40, EditQA())["status"], "FAIL")


class AdapterTests(unittest.TestCase):
    def test_existing_engine_timeline_preserves_windows(self):
        from vedit.model import Media
        data = job()
        plan = validate_job(data)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "source.mp4").write_bytes(b"probe is mocked")
            media = Media(id="media-test", path=str(root / "source.mp4"), duration=50, has_audio=True)
            with patch("vedit.store.probe_mod.probe", return_value=media):
                project = build_timeline(plan, root, data["render"])
            clips = [c for t in project.tracks for c in t.clips]
            self.assertEqual(len(clips), 1)
            self.assertEqual((clips[0].start, clips[0].in_, clips[0].duration), (0, 2, 40))
            media.duration = 20
            with patch("vedit.store.probe_mod.probe", return_value=media), self.assertRaises(WorkerError):
                build_timeline(plan, root, data["render"])

    def test_outputs_manifest_and_failure_gate(self):
        import json
        def render_fixture(project, options):
            Path(options.output).write_bytes(b"mock MP4 - not real render evidence")
        probe = {"format": {"duration": "40", "format_name": "mp4"}, "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("app.workers.audiovisual_worker.build_timeline"), patch("vedit.render.render", side_effect=render_fixture), patch("app.workers.audiovisual_worker.probe_video", return_value=probe), patch("app.workers.audiovisual_worker.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stderr = b""
                a = execute(job(), root, root / "out")
                other = copy.deepcopy(job())
                other.update(render_job_id=8, video_id=9)
                b = execute(other, root, root / "out")
                self.assertNotEqual(a, b)
                self.assertEqual(len(list(a.glob("*.mp4"))), 1)
                self.assertEqual(json.loads((a / "render-manifest.json").read_text())["video_id"], 2)
                with self.assertRaises(FileExistsError):
                    execute(job(), root, root / "out")
                other["render_job_id"] = 10
                run.return_value.returncode = 1
                with self.assertRaises(WorkerError):
                    execute(other, root, root / "out")
                failed = root / "out" / other["execution_id"] / "10"
                self.assertFalse((failed / "render-manifest.json").exists())
                self.assertEqual(json.loads((failed / "render-qa.json").read_text())["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
