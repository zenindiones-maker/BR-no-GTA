"""Security/lineage checks for one coherent owner reference across bounded critical-name segments."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.owner_voice_prompt_consistency_service import (
    select_single_owner_prompt_for_segments,
)


class OwnerCoherentReferenceContract(unittest.TestCase):
    def test_seven_segments_share_one_exact_item(self):
        anchor = object()
        prompts = select_single_owner_prompt_for_segments(
            anchor_prompt=anchor, segment_count=7, canonical_reference_sha256="c"*64,
        )
        self.assertEqual(len(prompts), 7)
        self.assertTrue(all(x is anchor for x in prompts))

    def test_eighteen_critical_names_share_one_owner_prompt(self):
        anchor = object()
        prompts = select_single_owner_prompt_for_segments(
            anchor_prompt=anchor, segment_count=18, canonical_reference_sha256="d"*64,
        )
        self.assertEqual(len(prompts), 18)
        self.assertTrue(all(prompt is anchor for prompt in prompts))

    def test_not_switchable_into_another_voice(self):
        anchor = object()
        other = object()
        prompts = select_single_owner_prompt_for_segments(
            anchor_prompt=anchor, segment_count=3, canonical_reference_sha256="a"*64,
        )
        self.assertTrue(all(x is not other for x in prompts))

    def test_missing_anchor_rejected(self):
        with self.assertRaisesRegex(ValueError, "CANONICAL"):
            select_single_owner_prompt_for_segments(
                anchor_prompt=None, segment_count=7, canonical_reference_sha256="a"*64,
            )

    def test_invalid_audio_provenance_rejected(self):
        for digest in ["", "not-a-sha", "A"*64, "a"*63]:
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                select_single_owner_prompt_for_segments(
                    anchor_prompt=object(), segment_count=7, canonical_reference_sha256=digest,
                )

    def test_unbounded_or_boolean_count_rejected(self):
        for count in (-1, 0, True, 65, "7"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                select_single_owner_prompt_for_segments(
                    anchor_prompt=object(), segment_count=count, canonical_reference_sha256="a"*64,
                )

    def test_existing_threshold_and_production_not_redefined(self):
        source = (Path(__file__).resolve().parents[1] /
                  "app/services/owner_voice_prompt_consistency_service.py").read_text()
        for forbidden in ("0.643708", "threshold_override", "approve_human_review",
                          "send_video", "activate_runtime", "voice_preset", "fallback_voice"):
            self.assertNotIn(forbidden, source)


from tempfile import TemporaryDirectory

from app.services.owner_voice_clone_step_output_service import (
    write_delivery_step_outputs,
    reject_critical_scope_for_standard_delivery,
)


class OwnerGitHubDeliveryOutputContract(unittest.TestCase):
    def test_critical_audio_routes_only_to_protected_delivery(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "github-output"
            output.write_text("", encoding="utf-8")
            manifest = Path(tmp) / "private-critical-manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            write_delivery_step_outputs(
                output_path=output, manifest_path=manifest,
                clone_id="BR_OWNER_V1_SINGLE_CLONE_900_1",
                send_eligible=True, critical_scope=True,
            )
            actual = dict(row.split("=", 1) for row in output.read_text().splitlines())
            self.assertEqual(actual["send_eligible"], "true")
            self.assertEqual(actual["critical_scope"], "true")
            self.assertEqual(actual["manifest_path"], str(manifest))
            self.assertEqual(actual["clone_id"], "BR_OWNER_V1_SINGLE_CLONE_900_1")

    def test_rejected_critical_audio_cannot_trigger_any_delivery(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "github-output"
            output.write_text("", encoding="utf-8")
            manifest = Path(tmp) / "private-critical-manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            write_delivery_step_outputs(
                output_path=output, manifest_path=manifest,
                clone_id="BR_OWNER_V1_SINGLE_CLONE_900_1",
                send_eligible=False, critical_scope=True,
            )
            actual = dict(row.split("=", 1) for row in output.read_text().splitlines())
            self.assertEqual(actual["send_eligible"], "false")
            self.assertEqual(actual["critical_scope"], "true")

    def test_reconciliation_is_control_only_and_not_critical_delivery(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "github-output"
            output.write_text("", encoding="utf-8")
            manifest = Path(tmp) / "private-control-manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            write_delivery_step_outputs(
                output_path=output, manifest_path=manifest,
                clone_id="BR_OWNER_V1_SINGLE_CLONE_900_1",
                send_eligible=True, critical_scope=False, control_only=True,
            )
            actual = dict(row.split("=", 1) for row in output.read_text().splitlines())
            self.assertEqual(actual["send_eligible"], "true")
            self.assertEqual(actual["critical_scope"], "false")

    def test_invalid_or_ambiguous_output_rejected_without_file_mutation(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "github-output"
            output.write_text("existing=receipt\\n", encoding="utf-8")
            manifest = Path(tmp) / "private-manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            for bad in (
                {"send_eligible": "true"},
                {"critical_scope": "true"},
                {"clone_id": "BR_OWNER_V1_SINGLE_CLONE_900_1\\nevil=1"},
                {"control_only": True, "critical_scope": True},
            ):
                data = dict(
                    output_path=output, manifest_path=manifest,
                    clone_id="BR_OWNER_V1_SINGLE_CLONE_900_1",
                    send_eligible=True, critical_scope=False, control_only=False,
                )
                data.update(bad)
                with self.subTest(bad=bad), self.assertRaises((ValueError, RuntimeError)):
                    write_delivery_step_outputs(**data)
                self.assertEqual(output.read_text(), "existing=receipt\\n")


class OwnerDeliveryScopeIsolationContract(unittest.TestCase):
    def test_critical_scope_rejected_by_standard_delivery_before_side_effect(self):
        with self.assertRaisesRegex(ValueError, "PROTECTED_DELIVERY_REQUIRED"):
            reject_critical_scope_for_standard_delivery({
                "schema_version":"OwnerVoiceSingleCloneCandidate/v1",
                "pronunciation_scope":"OWNER_GTA6_CRITICAL_NAMES_ONLY_V1",
                "clone_identity_gate":"PASS",
                "content_audio_prescreen":"PASS",
                "audition_delivery_eligible":True,
            })

    def test_control_only_and_ordinary_clones_keep_standard_delivery(self):
        reject_critical_scope_for_standard_delivery({
            "schema_version":"OwnerVoiceSingleCloneControlReconciliation/v1",
            "control_only":True,
        })
        reject_critical_scope_for_standard_delivery({
            "schema_version":"OwnerVoiceSingleCloneCandidate/v1",
            "pronunciation_scope":"LEGACY",
        })

    def test_delivery_script_applies_scope_guard_before_ledger_network_operations(self):
        source=Path("scripts/owner_voice_single_clone_delivery.py").read_text(encoding="utf-8")
        main=source.split("def main()->int:",1)[1]
        assert "reject_critical_scope_for_standard_delivery(manifest)" in main
        assert main.index("reject_critical_scope_for_standard_delivery(manifest)") < main.index(
            "store=store_from_environment("
        )


if __name__ == "__main__":
    unittest.main()
