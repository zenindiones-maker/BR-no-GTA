"""Reproduction: a deferred workflow dispatch must never masquerade as UNCHANGED.

No Telegram requests, GitHub secrets or workflow dispatches run in these tests.
"""
from __future__ import annotations

import json

import scripts.owner_voice_reference_handoff as handoff
from app.services.owner_voice_telegram_handoff_service import (
    build_owner_voice_reference_index,
    handoff_dispatch_key,
)


def _fake_owner_audio():
    return {
        "id": 12,
        "telegram_user_id": 77,
        "telegram_chat_id": -100123,
        "telegram_message_id": 234,
        "telegram_update_id": 456,
        "input_kind": "voice",
        "telegram_file_id": "SYNTHETIC",
        "telegram_file_unique_id": "SYNTHETIC-UNIQUE",
        "remote_verified": True,
    }


def _arrange(monkeypatch, tmp_path):
    control = tmp_path / "control.json"
    state = tmp_path / "handoff.json"
    control.write_text('{"allowed_user_id":77}', encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_CONTROL_STATE_FILE", str(control))
    monkeypatch.setenv("BR_OWNER_VOICE_HANDOFF_STATE_FILE", str(state))
    monkeypatch.setenv("BR_GITHUB_REPOSITORY", "zenindiones-maker/BR-no-GTA")
    monkeypatch.setenv("BR_GITHUB_BRANCH", "work/gate6f-analytics-learning")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "77")
    monkeypatch.setattr(handoff, "configured_allowed_chat_ids", lambda state: {-100123})
    monkeypatch.setattr(handoff, "list_recent_telegram_user_inputs",
                        lambda limit: [_fake_owner_audio()])
    monkeypatch.setattr(handoff, "_git_value", lambda *args: "a" * 40)
    index = build_owner_voice_reference_index(
        records=[_fake_owner_audio()],
        owner_user_id=77,
        allowed_chat_ids={-100123},
    )
    return state, index


def test_dispatch_deferred_reports_failure_instead_of_success(monkeypatch, tmp_path):
    state, index = _arrange(monkeypatch, tmp_path)
    calls = []
    def fake_dispatch(*args, **kwargs):
        calls.append("dispatch")
        return {"status": "SECRET_UPDATED_DISPATCH_DEFERRED"}
    monkeypatch.setattr(handoff, "handoff_reference_index_to_actions", fake_dispatch)
    assert handoff.main() != 0
    assert calls == ["dispatch"]
    persisted = json.loads(state.read_text(encoding="utf-8"))
    assert persisted["status"] == "SECRET_UPDATED_DISPATCH_DEFERRED"
    assert persisted["index_sha256"] == index["index_sha256"]


def test_deferred_same_index_blocks_unverified_redispatch(monkeypatch, tmp_path):
    state, index = _arrange(monkeypatch, tmp_path)
    state.write_text(json.dumps({
        "dispatch_key": handoff_dispatch_key(index["index_sha256"]),
        "status": "SECRET_UPDATED_DISPATCH_DEFERRED",
        "repository": "zenindiones-maker/BR-no-GTA",
        "branch": "work/gate6f-analytics-learning",
    }), encoding="utf-8")
    monkeypatch.setattr(
        handoff, "handoff_reference_index_to_actions",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("uncertain dispatch must not be blindly retried")),
    )
    assert handoff.main() != 0
    assert json.loads(state.read_text(encoding="utf-8"))["status"] == (
        "SECRET_UPDATED_DISPATCH_DEFERRED"
    )


def test_confirmed_dispatch_stays_idempotent(monkeypatch, tmp_path):
    state, index = _arrange(monkeypatch, tmp_path)
    state.write_text(json.dumps({
        "dispatch_key": handoff_dispatch_key(index["index_sha256"]),
        "status": "DISPATCHED",
        "repository": "zenindiones-maker/BR-no-GTA",
        "branch": "work/gate6f-analytics-learning",
    }), encoding="utf-8")
    monkeypatch.setattr(
        handoff, "handoff_reference_index_to_actions",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("duplicate workflow dispatch")),
    )
    assert handoff.main() == 0
