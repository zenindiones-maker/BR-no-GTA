from pathlib import Path
import subprocess

import pytest

from app.services.codex_addy_capability_executor import execute_codex_addy_capability
from app.services.agent_office.codex_auth import CodexAuthenticationProvider
from app.services.agent_office.codex_bounded_worker import (
    CODEX_SHELL_ENVIRONMENT_POLICY_ARGS,
)
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_capability_service import (
    CapabilityDefinition,
    CapabilityExecutionBlocked,
)


def capability():
    return CapabilityDefinition(
        capability_id="addy:code-review-and-quality",
        provider="addy-agent-skills",
        execution_kind="codex_native_skill",
        allowed_actions=("DEVELOPMENT",),
        tags=("code", "review", "quality"),
    )


def repo(tmp_path: Path):
    root=tmp_path/'repo'; root.mkdir()
    subprocess.run(['git','init'],cwd=root,check=True,capture_output=True)
    (root/'sample.py').write_text('VALUE = 1\n')
    subprocess.run(['git','add','sample.py'],cwd=root,check=True)
    return root


def auth():
    return issue_harness_authorization(
        authorized_action='DEVELOPMENT',
        subject='capability:addy:code-review-and-quality',
        harness_decision_id='decision-canary',
        execution_id='execution-canary',
    )


def test_missing_codex_auth_is_blocked_before_model_turn(tmp_path):
    root=repo(tmp_path); calls=[]
    def runner(command, **kwargs):
        calls.append(command)
        assert command == ['codex','login','status']
        return subprocess.CompletedProcess(command,1,stdout='',stderr='sensitive detail')
    with pytest.raises(CapabilityExecutionBlocked) as caught:
        execute_codex_addy_capability(
            capability(),
            {'task':'Review sample.py without modifying it.'},
            runner=runner,
            repository_root=root,
        )
    assert calls == [['codex','login','status']]
    assert caught.value.stage == 'authentication'
    assert caught.value.safe_message == 'Codex authentication is not available in the ephemeral runner'
    assert caught.value.boundary == 'Codex authentication prerequisite missing; no model turn started'
    assert 'sensitive' not in str(caught.value)


def test_authenticated_executor_invokes_exactly_one_selected_skill(tmp_path):
    root=repo(tmp_path); calls=[]
    def runner(command, **kwargs):
        calls.append(command)
        if command == ['codex','login','status']:
            return subprocess.CompletedProcess(command,0,stdout='logged in',stderr='')
        assert command[:2] == ['codex','exec']
        assert '@code-review-and-quality' in command[-1]
        assert '@using-agent-skills' not in command[-1]
        return subprocess.CompletedProcess(command,0,stdout='{"item":{"type":"agent_message","text":"bounded review"}}\n',stderr='')
    result=execute_codex_addy_capability(
        capability(),
        {'task':'Review sample.py without modifying it.'},
        runner=runner,
        repository_root=root,
    )
    assert len(calls) == 2
    assert result['skill'] == 'code-review-and-quality'
    assert result['output'] == 'bounded review'
    assert not (root/'temporary-change.txt').exists()


class _StubAuthProvider(CodexAuthenticationProvider):
    def __init__(self, statuses, *, environ=None):
        super().__init__(
            environ=environ or {"PATH": "/usr/bin", "ZERO_COST_OPERATION": "TRUE"}
        )
        self.statuses = list(statuses)
        self.commands = []

    def _status(self, *, cwd: Path, timeout: float, env):
        code, out = self.statuses.pop(0)
        return subprocess.CompletedProcess(
            ["codex", "login", "status"], code, stdout=out, stderr=""
        )

    def _run(self, command, *, cwd: Path, timeout: float, env, passthrough=False):
        self.commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def test_agent_office_missing_auth_blocks_before_model_turn(tmp_path):
    state = _StubAuthProvider([(1, "")]).bootstrap(cwd=tmp_path)
    assert state.available is False
    assert state.user_action_required is True


def test_agent_office_existing_supported_auth_is_available(tmp_path):
    state = _StubAuthProvider([(0, "Logged in using ChatGPT")]).bootstrap(cwd=tmp_path)
    assert state.available is True
    assert state.user_action_required is False


def test_agent_office_device_auth_rechecks_same_runner_state(tmp_path):
    provider = _StubAuthProvider([(1, ""), (0, "Logged in using ChatGPT")])
    state = provider.bootstrap(cwd=tmp_path, allow_device_auth=True)
    assert state.available is True
    assert state.method == "device_auth"
    assert provider.commands == [["codex", "login", "--device-auth"]]


def test_agent_office_zero_cost_rejects_existing_paid_api_session(tmp_path):
    state = _StubAuthProvider([(0, "Logged in using API key")]).bootstrap(cwd=tmp_path)
    assert state.available is False
    assert state.cost_class == "paid_api"
    assert state.user_action_required is True


def test_agent_office_model_command_environment_policy_is_allowlisted():
    assert CODEX_SHELL_ENVIRONMENT_POLICY_ARGS == (
        "--config",
        "shell_environment_policy.ignore_default_excludes=false",
        "--config",
        'shell_environment_policy.include_only=["PATH","USER","LOGNAME","LANG","LC_ALL","LC_CTYPE","TERM","TMPDIR","TEMP","TMP","PYTHONPATH","SHELL"]',
    )
