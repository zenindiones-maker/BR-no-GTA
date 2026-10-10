"""Real DeepSeek Harness public MCP entrypoint must not self-issue REA grants."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from app.database.connection import get_connection
from app.database.schema import initialize_schema


class PublicReaBoundaryTests(unittest.TestCase):
    def test_public_unauthenticated_rea_request_is_blocked_before_grant(self):
        from app.integrations.deepseek_harness import server

        with tempfile.TemporaryDirectory(prefix="br-rea-public-gate-") as temp:
            old = os.environ.get("BR_TEST_DATABASE")
            os.environ["BR_TEST_DATABASE"] = str(Path(temp) / "harness.sqlite")
            try:
                initialize_schema()
                with get_connection() as db:
                    before = db.execute("SELECT count(*) FROM harness_authorizations").fetchone()[0]

                observed = json.loads(server.br_capability_execute(
                    capability_id="reverse-engineering.evidence.inspect",
                    authorized_action="DEVELOPMENT",
                    harness_decision_id="attacker-caller-assertion",
                    execution_id="attacker-execution",
                    payload_json=json.dumps({
                        "paths": ["app/services/harness_capability_service.py"],
                        "authorization_id": "attacker-forged",
                        "harness_decision_id": "attacker-caller-assertion",
                        "execution_id": "attacker-execution",
                    }),
                ))
                self.assertEqual(observed["result"]["status"], "BLOCKED")
                self.assertFalse(observed["result"]["active"])
                self.assertEqual(
                    observed["result"]["result"]["reason"],
                    "MCP_CALLER_NOT_INDEPENDENTLY_AUTHENTICATED",
                )
                with get_connection() as db:
                    after = db.execute("SELECT count(*) FROM harness_authorizations").fetchone()[0]
                self.assertEqual(after, before, "Public call must not issue any grant")
            finally:
                if old is None:
                    os.environ.pop("BR_TEST_DATABASE", None)
                else:
                    os.environ["BR_TEST_DATABASE"] = old


if __name__ == "__main__":
    unittest.main()
