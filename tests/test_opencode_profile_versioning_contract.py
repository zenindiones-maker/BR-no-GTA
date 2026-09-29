from __future__ import annotations

from hashlib import sha256
import json
import os
import tempfile
import unittest

from app.database.harness_learning_repository import (
    activate_version,
    get_version,
    insert_version,
)
from app.database.schema import initialize_schema
from app.services.opencode_executor_profile_service import (
    BASELINE_OPENCODE_EXECUTOR_VERSION,
    CANDIDATE_OPENCODE_EXECUTOR_VERSION,
    OPENCODE_EXECUTOR_SKILL_ID,
    executable_opencode_executor_profile,
)
from scripts.hydrate_promoted_opencode_profile import hydrate


def _canonical(value: dict) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _legacy_promoted_v2_checksum() -> str:
    legacy = {
        "executor_kind": "official_opencode_cli_github_actions",
        "executor_binding": (
            "app.services.opencode_native_ai_provider.OpenCodeNativeAIProvider"
        ),
        "canonical_model": "oc/big-pickle",
        "executor_model": "opencode/big-pickle",
        "workflow": "omniroute.yml",
        "cli_version": "2.0.8",
        "status": "PROMOTED",
        "evidence_run_id": 35450516329,
    }
    return sha256(_canonical(legacy).encode("utf-8")).hexdigest()


def _insert_legacy_promoted_v2() -> dict:
    initialize_schema()
    canonical = executable_opencode_executor_profile(
        CANDIDATE_OPENCODE_EXECUTOR_VERSION
    )
    return insert_version(
        table="harness_skill_versions",
        identity_field="skill_id",
        record={
            "skill_id": OPENCODE_EXECUTOR_SKILL_ID,
            "version": CANDIDATE_OPENCODE_EXECUTOR_VERSION,
            "parent_version": BASELINE_OPENCODE_EXECUTOR_VERSION,
            "content_ref": canonical["content_ref"],
            "checksum": _legacy_promoted_v2_checksum(),
            "status": "ACTIVE",
            "evidence_refs": [
                "github:run:35450516329:legacy-promotion-metadata-in-definition",
            ],
            "created_at": "2026-09-19T14:40:18.249249+00:00",
            "promoted_at": "2026-09-19T14:40:18.249249+00:00",
        },
    )


class OpenCodeProfileVersioningContractTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="opencode-profile-test-")
        self._previous_db = os.environ.get("BR_TEST_DATABASE")
        os.environ["BR_TEST_DATABASE"] = os.path.join(self._tmp.name, "profile.db")

    def tearDown(self):
        if self._previous_db is None:
            os.environ.pop("BR_TEST_DATABASE", None)
        else:
            os.environ["BR_TEST_DATABASE"] = self._previous_db
        self._tmp.cleanup()

    def test_legacy_v2_promotion_metadata_drift_is_explicitly_migrated_without_overwrite(self):
        before = _insert_legacy_promoted_v2()

        result = hydrate()

        after = get_version(
            table="harness_skill_versions",
            identity_field="skill_id",
            identity=OPENCODE_EXECUTOR_SKILL_ID,
            version=CANDIDATE_OPENCODE_EXECUTOR_VERSION,
        )
        canonical = executable_opencode_executor_profile(
            CANDIDATE_OPENCODE_EXECUTOR_VERSION
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            result["profile_definition_compatibility"],
            "KNOWN_LEGACY_PROMOTION_METADATA_DRIFT",
        )
        self.assertFalse(result["profile_migration_required"])
        self.assertEqual(result["active_profile"]["version"], "v2")
        self.assertEqual(result["active_profile"]["checksum"], canonical["checksum"])
        self.assertEqual(
            before["checksum"],
            after["checksum"],
            _legacy_promoted_v2_checksum(),
        )
        self.assertEqual(after["content_ref"], before["content_ref"])

    def test_unknown_same_version_checksum_conflict_still_fails_closed(self):
        initialize_schema()
        canonical = executable_opencode_executor_profile(
            CANDIDATE_OPENCODE_EXECUTOR_VERSION
        )
        insert_version(
            table="harness_skill_versions",
            identity_field="skill_id",
            record={
                "skill_id": OPENCODE_EXECUTOR_SKILL_ID,
                "version": CANDIDATE_OPENCODE_EXECUTOR_VERSION,
                "parent_version": BASELINE_OPENCODE_EXECUTOR_VERSION,
                "content_ref": canonical["content_ref"],
                "checksum": "0" * 64,
                "status": "ACTIVE",
                "evidence_refs": ["test:unknown-profile-conflict"],
                "created_at": "2026-09-19T14:40:18.249249+00:00",
                "promoted_at": "2026-09-19T14:40:18.249249+00:00",
            },
        )

        with self.assertRaisesRegex(RuntimeError, "AGENT_PROFILE_VERSION_CONFLICT"):
            hydrate()

    def test_promotion_pointer_change_does_not_mutate_immutable_definition_checksum(self):
        initialize_schema()
        canonical = executable_opencode_executor_profile(
            CANDIDATE_OPENCODE_EXECUTOR_VERSION
        )
        insert_version(
            table="harness_skill_versions",
            identity_field="skill_id",
            record={
                "skill_id": OPENCODE_EXECUTOR_SKILL_ID,
                "version": CANDIDATE_OPENCODE_EXECUTOR_VERSION,
                "parent_version": BASELINE_OPENCODE_EXECUTOR_VERSION,
                "content_ref": canonical["content_ref"],
                "checksum": canonical["checksum"],
                "status": "CANDIDATE",
                "evidence_refs": ["test:immutable-definition"],
                "created_at": "2026-09-19T14:40:18.249249+00:00",
                "promoted_at": None,
            },
        )

        activate_version(
            table="harness_skill_versions",
            identity_field="skill_id",
            identity=OPENCODE_EXECUTOR_SKILL_ID,
            version=CANDIDATE_OPENCODE_EXECUTOR_VERSION,
            promoted_at="2026-09-19T14:40:18.249249+00:00",
        )

        promoted = get_version(
            table="harness_skill_versions",
            identity_field="skill_id",
            identity=OPENCODE_EXECUTOR_SKILL_ID,
            version=CANDIDATE_OPENCODE_EXECUTOR_VERSION,
        )
        self.assertEqual(promoted["status"], "ACTIVE")
        self.assertEqual(promoted["checksum"], canonical["checksum"])

    def test_legacy_compatibility_hydration_is_idempotent(self):
        _insert_legacy_promoted_v2()

        first = hydrate()
        second = hydrate()

        self.assertEqual(first["status"], second["status"])
        self.assertEqual(first["status"], "PASS")
        self.assertEqual(
            first["profile_definition_compatibility"],
            "KNOWN_LEGACY_PROMOTION_METADATA_DRIFT",
        )
        self.assertEqual(
            second["profile_definition_compatibility"],
            "KNOWN_LEGACY_PROMOTION_METADATA_DRIFT",
        )


if __name__ == "__main__":
    unittest.main()
