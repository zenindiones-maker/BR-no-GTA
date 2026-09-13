"""Transport regression only; these fixtures are not authorized canary inputs."""
import copy
import unittest
from app.services.video_service import create_video_spec
from app.services.video_execution_service import create_video_execution_spec
from app.services.render_job_service import create_render_job


class EditPlanTransportTests(unittest.TestCase):
    def test_whole_plan_and_scene_words_survive_without_shared_mutation(self):
        scene = dict(order=1, narrative_block="test", narration="test",
                     visual_type="video", visual_description="test",
                     duration_seconds=30, requirements=[], segment_id=7,
                     content_unit_id=8, media_path="source.mp4",
                     asset_ref="remote://media-worker/gta6-trailer",
                     source_url="https://example.test/gta6-trailer",
                     source_start_seconds=2, source_end_seconds=32,
                     transcript_words=[dict(word="test", start=2, end=3)])
        plan = dict(version="1", content_item_id=1, script_id=2, title="test",
                    objective="test", format="video", duration_seconds=30,
                    tracks=[dict(name="V1", kind="video", clips=[dict(
                        segment_id=7, content_unit_id=8, media_path="source.mp4",
                        track="V1", start_seconds=0, source_start_seconds=2,
                        duration_seconds=30)])], audio=[], metadata={"test_only": True})
        production = dict(content_item_id=1, script_id=2, idea_id=3,
                          objective="test", format="video", estimated_duration_seconds=30,
                          scenes=[scene], audio_requirements=[], visual_requirements=[],
                          edit_plan=plan)
        original = copy.deepcopy(production)
        auth = dict(brain_decision_id="test-decision", execution_id="test-execution",
                    authorized_action="EXECUTION")
        video = create_video_spec(production, brain_decision=auth)
        execution = create_video_execution_spec(video)
        job = create_render_job(execution, video_id=9)
        for output in (video, execution, job):
            self.assertEqual(output["edit_plan"], plan)
            for key, value in auth.items():
                self.assertEqual(output[key], value)
            for key in (
                "segment_id",
                "content_unit_id",
                "media_path",
                "asset_ref",
                "source_url",
                "source_start_seconds",
                "source_end_seconds",
                "transcript_words",
            ):
                self.assertEqual(
                    output["scenes"][0][key],
                    scene[key],
                )

            self.assertEqual(
                output["scenes"][0]["media_path"],
                "source.mp4",
            )
            self.assertEqual(
                output["scenes"][0]["asset_ref"],
                "remote://media-worker/gta6-trailer",
            )
            self.assertNotEqual(
                output["scenes"][0]["media_path"],
                output["scenes"][0]["asset_ref"],
            )
        job["edit_plan"]["tracks"][0]["clips"][0]["media_path"] = "changed"
        job["scenes"][0]["transcript_words"][0]["word"] = "changed"
        self.assertEqual(production, original)
        self.assertEqual(execution["edit_plan"], plan)

    def test_video_spec_rejects_missing_authority(self):
        with self.assertRaises(ValueError):
            create_video_spec(dict(content_item_id=1, script_id=2, idea_id=3,
                                  objective="test", format="video", estimated_duration_seconds=30,
                                  scenes=[{}], audio_requirements=[], visual_requirements=[]))
