from pathlib import Path
import subprocess

import pytest

import scripts.bootstrap_hermes_agent as bootstrap


def test_pinned_fetch_retries_once_for_transient_network_failure(monkeypatch, tmp_path):
    calls = []

    def fake_run(*args, cwd=None):
        calls.append((args, cwd))
        if len(calls) == 1:
            raise subprocess.CalledProcessError(
                128,
                list(args),
                stderr="fatal: unable to access upstream: The requested URL returned error: 503",
            )
        return ""

    monkeypatch.setattr(bootstrap, "_run", fake_run)
    monkeypatch.setattr(bootstrap.time, "sleep", lambda _seconds: None)

    bootstrap._fetch_pinned_commit(tmp_path, "a" * 40)

    assert len(calls) == 2


def test_pinned_fetch_does_not_retry_deterministic_git_failure(monkeypatch, tmp_path):
    calls = []

    def fake_run(*args, cwd=None):
        calls.append((args, cwd))
        raise subprocess.CalledProcessError(
            128,
            list(args),
            stderr="fatal: couldn't find remote ref deadbeef",
        )

    monkeypatch.setattr(bootstrap, "_run", fake_run)

    with pytest.raises(RuntimeError, match="transient=FALSE"):
        bootstrap._fetch_pinned_commit(tmp_path, "b" * 40)

    assert len(calls) == 1
