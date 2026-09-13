"""Synthetic technical integration only; NEVER authorized RUN-001 evidence."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.cloud_worker_fixtures import job
from app.workers.audiovisual_worker import execute


@unittest.skipUnless(os.environ.get("CLOUD_RENDER_INTEGRATION") == "1",
                     "Real FFmpeg integration runs on GitHub Actions only")
class CloudRenderIntegration(unittest.TestCase):
    def test_two_independent_real_engine_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=320x180:rate=25", "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=48000", "-t", "4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                str(root / "source.mp4"),
            ], check=True, timeout=60)
            folders = []
            for number in (1, 2):
                data = job()
                data.update(render_job_id=number, video_id=number,
                            execution_id=f"synthetic-test-{number}",
                            estimated_duration_seconds=2)
                data["render"].update(resolution="320x180", fps=25)
                data["edit_plan"]["duration_seconds"] = 2
                clip = data["edit_plan"]["tracks"][0]["clips"][0]
                clip.update(source_start_seconds=1, duration_seconds=2)
                folder = execute(data, root, root / "out")
                folders.append(folder)
                manifest = json.loads((folder / "render-manifest.json").read_text())
                qa = json.loads((folder / "render-qa.json").read_text())
                self.assertEqual(manifest["qa_status"], "PASS")
                self.assertEqual(len(manifest["sha256"]), 64)
                self.assertTrue(qa["checks"]["full_decode"])
                self.assertEqual(len(list(folder.glob("*.mp4"))), 1)
                self.assertEqual(manifest["video_id"], number)
                self.assertAlmostEqual(manifest["duration_seconds"], 2, delta=.5)
            self.assertNotEqual(*folders)
            evidence_dir = os.environ.get("CLOUD_TEST_EVIDENCE_DIR")
            if evidence_dir:
                # Copy only completed output bundles, never source assets or secrets.
                destination = Path(evidence_dir)
                shutil.copytree(root / "out", destination)
                (destination / "TEST_ONLY.txt").write_text(
                    "SYNTHETIC TECHNICAL TEST. NOT AUTHORIZED RUN-001 CANARY.\n")
