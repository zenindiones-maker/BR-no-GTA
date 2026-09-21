from pathlib import Path
import subprocess

import pytest

from app.services.codex_addy_capability_executor import execute_codex_addy_capability
from app.services.agent_office.codex_auth import CodexAuthenticationProvider
from app.services.agent_office.codex_auth_control import (
    AUTH_AVAILABLE,
    AUTH_BLOCKED,
    AUTH_UNAVAILABLE,
    AUTH_USER_ACTION_REQUIRED,
    build_mission_checkpoint,
    classify_codex_auth,
    load_checkpoint,
    resolve_checkpoint_after_auth,
    write_checkpoint,
)
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
            environ=environ
            or {
                "PATH": "/usr/bin",
                "ZERO_COST_OPERATION": "TRUE",
                "TELEGRAM_BOT_TOKEN": "test-only-token",
                "TELEGRAM_ALLOWED_USER_ID": "test-only-user",
                "GITHUB_RUN_ID": "1",
            }
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

    def _device_auth_private(self, *, cwd: Path, timeout: float, env):
        self.commands.append(["codex", "login", "--device-auth"])
        return 0


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



def _provider_factory(statuses):
    def factory(*, environ=None):
        return _StubAuthProvider(list(statuses), environ=environ)
    return factory


def test_auth_control_preflight_existing_auth_continues(tmp_path):
    state = classify_codex_auth(
        mission_id="mission-auth-available",
        cwd=tmp_path,
        environ={
            "PATH": "/usr/bin",
            "ZERO_COST_OPERATION": "TRUE",
            "TELEGRAM_ALLOWED_USER_ID": "12345",
        },
        provider_factory=_provider_factory([(0, "Logged in using ChatGPT")]),
    )
    assert state.state == AUTH_AVAILABLE
    assert state.auth_available is True
    assert state.user_action_required is False
    assert state.lease is not None
    assert state.lease.credential_material_persisted is False
    assert state.failure_memory_retrieved is True
    assert state.auth_timeout_path_repeated is False


def test_auth_control_missing_cloud_wif_is_not_misreported_as_local_login_request(tmp_path):
    state = classify_codex_auth(
        mission_id="mission-auth-human-gate",
        cwd=tmp_path,
        environ={
            "PATH": "/usr/bin",
            "ZERO_COST_OPERATION": "TRUE",
            "TELEGRAM_ALLOWED_USER_ID": "12345",
        },
        provider_factory=_provider_factory([(1, "")]),
    )
    assert state.state == AUTH_BLOCKED
    assert state.auth_available is False
    assert state.user_action_required is False
    assert state.local_codex_auth_context == "SEPARATE_USER_CONTEXT"
    assert state.cloud_runner_codex_auth_context == "EPHEMERAL_RUNNER"
    assert state.missing_auth_configuration == (
        "OPENAI_FEDERATION_RULE_ID",
        "OPENAI_IDENTITY_TOKEN_FILE",
        "OPENAI_FEDERATION_AUDIENCE",
    )
    assert "does not invalidate or disconnect" in state.reason
    assert state.auth_timeout_path_repeated is False

    checkpoint = build_mission_checkpoint(
        dispatch_id="dispatch-auth-human",
        mission_id="mission-auth-human-gate",
        target_ref="work/gate6f-analytics-learning",
        target_sha="a" * 40,
        plan_b64="cGxhbg==",
        human_goal_b64="Z29hbA==",
        telegram_chat_id="12345",
        preflight=state,
    )
    path = tmp_path / "checkpoint.json"
    write_checkpoint(path, checkpoint)
    persisted = load_checkpoint(path)
    assert persisted["mission_id"] == "mission-auth-human-gate"
    assert persisted["credential_material_persisted"] is False
    raw = path.read_text(encoding="utf-8").lower()
    assert "access_token" not in raw
    assert "refresh_token" not in raw
    assert "user_code" not in raw
    assert "api_key" not in raw


def test_auth_control_unavailable_without_paired_human_fails_fast(tmp_path):
    state = classify_codex_auth(
        mission_id="mission-auth-no-human",
        cwd=tmp_path,
        environ={
            "PATH": "/usr/bin",
            "ZERO_COST_OPERATION": "TRUE",
        },
        provider_factory=_provider_factory([(1, "")]),
    )
    assert state.state == AUTH_BLOCKED
    assert state.auth_available is False
    assert state.user_action_required is False
    assert state.paired_human_available is False
    assert state.delivery_surface == "NONE"
    assert state.auth_timeout_path_repeated is False


def test_auth_gate_resolves_and_resumes_same_checkpoint_after_auth_available(tmp_path):
    unavailable = classify_codex_auth(
        mission_id="mission-auth-resume",
        cwd=tmp_path,
        environ={
            "PATH": "/usr/bin",
            "ZERO_COST_OPERATION": "TRUE",
            "TELEGRAM_ALLOWED_USER_ID": "12345",
        },
        provider_factory=_provider_factory([(1, "")]),
    )
    checkpoint = build_mission_checkpoint(
        dispatch_id="dispatch-auth-resume",
        mission_id="mission-auth-resume",
        target_ref="work/gate6f-analytics-learning",
        target_sha="b" * 40,
        plan_b64="cGxhbg==",
        human_goal_b64="Z29hbA==",
        telegram_chat_id="12345",
        preflight=unavailable,
    )
    path = tmp_path / "checkpoint.json"
    write_checkpoint(path, checkpoint)

    resumed = resolve_checkpoint_after_auth(
        checkpoint_path=path,
        cwd=tmp_path,
        environ={
            "PATH": "/usr/bin",
            "ZERO_COST_OPERATION": "TRUE",
            "TELEGRAM_ALLOWED_USER_ID": "12345",
        },
        provider_factory=_provider_factory([(0, "Logged in using ChatGPT")]),
    )
    assert resumed["AUTH_GATE_RESOLVED"] == "PASS"
    assert resumed["MISSION_RESUMED_FROM_CHECKPOINT"] == "PASS"
    assert resumed["mission_id"] == "mission-auth-resume"
    assert resumed["target_sha"] == "b" * 40
    assert resumed["credential_material_persisted"] is False


def test_legacy_device_auth_refuses_review_group_fallback(tmp_path):
    provider = _StubAuthProvider(
        [(1, "")],
        environ={
            "PATH": "/usr/bin",
            "ZERO_COST_OPERATION": "TRUE",
            "TELEGRAM_BOT_TOKEN": "test-only-token",
            "TELEGRAM_REVIEW_CHAT_ID": "review-group-only",
            "GITHUB_RUN_ID": "1",
        },
    )
    state = provider.bootstrap(cwd=tmp_path, allow_device_auth=True, timeout=0.01)
    assert state.available is False
    assert state.method == "device_auth"
    assert state.user_action_required is True
    assert provider.commands == []
