from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent-tooling" / "claude_auth_preflight.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "claude-code-auth-validation.yml"


class ClaudeAuthBoundaryTests(unittest.TestCase):
    def _run(self, *, oauth="", api_key="", auth_status=0):
        with tempfile.TemporaryDirectory() as tmp:
            fake_bin = Path(tmp)
            claude = fake_bin / "claude"
            claude.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1\" == \"auth\" && \"$2\" == \"status\" ]]; then\n"
                f"  exit {auth_status}\n"
                "fi\n"
                "exit 99\n",
                encoding="utf-8",
            )
            claude.chmod(0o755)
            env = os.environ.copy()
            env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
            env.pop("ANTHROPIC_API_KEY", None)
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            if oauth:
                env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth
            if api_key:
                env["ANTHROPIC_API_KEY"] = api_key
            return subprocess.run(
                ["bash", str(SCRIPT)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

    def test_missing_credential_fails_closed(self):
        result = self._run()
        self.assertEqual(result.returncode, 2)
        self.assertIn("REASON=MISSING_CREDENTIAL", result.stderr)

    def test_ambiguous_credentials_fail_closed_without_leaking_values(self):
        oauth = "oauth-secret-value"
        api_key = "api-secret-value"
        result = self._run(oauth=oauth, api_key=api_key)
        self.assertEqual(result.returncode, 2)
        combined = result.stdout + result.stderr
        self.assertIn("REASON=AMBIGUOUS_CREDENTIALS", combined)
        self.assertNotIn(oauth, combined)
        self.assertNotIn(api_key, combined)

    def test_oauth_subscription_auth_passes_without_leaking_token(self):
        token = "oauth-secret-value"
        result = self._run(oauth=token)
        self.assertEqual(result.returncode, 0)
        self.assertIn("CLAUDE_CODE_AUTH_METHOD=OAUTH_SUBSCRIPTION", result.stdout)
        self.assertIn("CLAUDE_CODE_AUTH_STATUS=PASS", result.stdout)
        self.assertNotIn(token, result.stdout + result.stderr)

    def test_api_key_auth_passes_without_leaking_key(self):
        key = "api-secret-value"
        result = self._run(api_key=key)
        self.assertEqual(result.returncode, 0)
        self.assertIn("CLAUDE_CODE_AUTH_METHOD=ANTHROPIC_API_KEY", result.stdout)
        self.assertIn("CLAUDE_CODE_AUTH_STATUS=PASS", result.stdout)
        self.assertNotIn(key, result.stdout + result.stderr)

    def test_rejected_auth_status_fails_without_model_call(self):
        result = self._run(oauth="oauth-secret-value", auth_status=1)
        self.assertEqual(result.returncode, 1)
        self.assertIn("REASON=AUTH_STATUS_REJECTED", result.stderr)

    def test_workflow_maps_only_repository_secrets_and_runs_no_prompt(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("secrets.CLAUDE_CODE_OAUTH_TOKEN", text)
        self.assertIn("secrets.ANTHROPIC_API_KEY", text)
        self.assertIn("claude_auth_preflight.sh", text)
        self.assertNotIn("claude -p", text)
        self.assertNotIn("dangerously-skip-permissions", text)


if __name__ == "__main__":
    unittest.main()
