from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from workstation_runtime.lease import (
    LeaseConflict,
    LeaseStore,
    MediaLease,
)
from workstation_runtime.lifecycle import (
    AwsApiError,
    BudgetBlocked,
    LifecycleController,
)
from workstation_runtime.reaper_render import (
    RenderFailure,
    run_reaper_render,
)
from workstation_runtime.shutdown_guard import (
    ShutdownDecision,
    evaluate_shutdown,
)
from workstation_runtime.validation import (
    CrossIsolationError,
    DriverUnavailable,
    NvencUnavailable,
    assert_cross_project_denied,
    assert_gpu_driver,
    assert_nvenc_encode,
)


UTC = timezone.utc


class FakeEc2:
    def __init__(self, state: str = "stopped", *, fail: bool = False):
        self.state = state
        self.fail = fail
        self.starts = 0
        self.stops = 0

    def describe_state(self, instance_id: str) -> str:
        if self.fail:
            raise RuntimeError("aws unavailable")
        return self.state

    def start(self, instance_id: str) -> None:
        if self.fail:
            raise RuntimeError("aws unavailable")
        self.starts += 1
        self.state = "running"

    def stop(self, instance_id: str) -> None:
        if self.fail:
            raise RuntimeError("aws unavailable")
        self.stops += 1
        self.state = "stopped"


class FakeBudget:
    def __init__(self, ready: bool):
        self.ready = ready

    def guardrail_ready(self, project: str) -> bool:
        return self.ready


def test_start_stop_are_idempotent() -> None:
    ec2 = FakeEc2("stopped")
    ctl = LifecycleController(ec2=ec2, budget=FakeBudget(True))
    assert ctl.start("hazewave", "i-1") == "running"
    assert ctl.start("hazewave", "i-1") == "running"
    assert ec2.starts == 1
    assert ctl.stop("hazewave", "i-1") == "stopped"
    assert ctl.stop("hazewave", "i-1") == "stopped"
    assert ec2.stops == 1


def test_start_fails_closed_without_budget() -> None:
    ctl = LifecycleController(ec2=FakeEc2("stopped"), budget=FakeBudget(False))
    with pytest.raises(BudgetBlocked, match="BLOCKED_BUDGET_POLICY"):
        ctl.start("hazewave", "i-1")


def test_aws_api_error_is_explicit() -> None:
    ctl = LifecycleController(ec2=FakeEc2(fail=True), budget=FakeBudget(True))
    with pytest.raises(AwsApiError, match="BLOCKED_AWS_AUTH_OR_API"):
        ctl.status("i-1")


def test_lease_acquire_release_and_duplicate_request(tmp_path: Path) -> None:
    store = LeaseStore(tmp_path)
    now = datetime(2026, 10, 5, 18, 0, tzinfo=UTC)
    lease = MediaLease(
        request_id="req-1",
        project="hazewave",
        capability="audio.reaper.render",
        expires_at=now + timedelta(minutes=10),
    )
    store.acquire(lease, now=now)
    assert store.active(now=now) == [lease]
    with pytest.raises(LeaseConflict, match="DUPLICATE_EXECUTION_REQUEST"):
        store.acquire(lease, now=now)
    store.release("req-1")
    assert store.active(now=now) == []


def test_lease_state_survives_process_restart(tmp_path: Path) -> None:
    now = datetime(2026, 10, 5, 18, 0, tzinfo=UTC)
    lease = MediaLease(
        request_id="req-2",
        project="br-no-gta",
        capability="media.ffmpeg.encode",
        expires_at=now + timedelta(minutes=5),
    )
    LeaseStore(tmp_path).acquire(lease, now=now)
    reloaded = LeaseStore(tmp_path)
    assert reloaded.active(now=now)[0].request_id == "req-2"


def test_idle_shutdown_requires_every_guard_to_be_clear() -> None:
    now = datetime(2026, 10, 5, 18, 0, tzinfo=UTC)
    base = dict(
        now=now,
        booted_at=now - timedelta(hours=1),
        last_activity_at=now - timedelta(minutes=40),
        idle_timeout=timedelta(minutes=30),
        max_runtime=timedelta(hours=8),
    )
    assert evaluate_shutdown(
        **base,
        interactive_active=False,
        active_leases=0,
        protected_render_active=False,
    ) == ShutdownDecision.STOP_IDLE

    assert evaluate_shutdown(
        **base,
        interactive_active=True,
        active_leases=0,
        protected_render_active=False,
    ) == ShutdownDecision.KEEP_INTERACTIVE

    assert evaluate_shutdown(
        **base,
        interactive_active=False,
        active_leases=1,
        protected_render_active=False,
    ) == ShutdownDecision.KEEP_LEASE

    assert evaluate_shutdown(
        **base,
        interactive_active=False,
        active_leases=0,
        protected_render_active=True,
    ) == ShutdownDecision.KEEP_PROTECTED_RENDER


def test_max_runtime_never_kills_protected_render_or_lease() -> None:
    now = datetime(2026, 10, 5, 18, 0, tzinfo=UTC)
    args = dict(
        now=now,
        booted_at=now - timedelta(hours=9),
        last_activity_at=now,
        idle_timeout=timedelta(minutes=30),
        max_runtime=timedelta(hours=8),
        interactive_active=True,
    )
    assert evaluate_shutdown(
        **args, active_leases=1, protected_render_active=False
    ) == ShutdownDecision.KEEP_LEASE
    assert evaluate_shutdown(
        **args, active_leases=0, protected_render_active=True
    ) == ShutdownDecision.KEEP_PROTECTED_RENDER
    assert evaluate_shutdown(
        **args, active_leases=0, protected_render_active=False
    ) == ShutdownDecision.STOP_MAX_RUNTIME


def test_reaper_render_receipt_hashes_input_and_output(tmp_path: Path) -> None:
    project = tmp_path / "mix.rpp"
    project.write_text("RPP", encoding="utf-8")
    output = tmp_path / "render.wav"
    output.write_bytes(b"RIFFfake-wave")

    class Runner:
        def __call__(self, argv: list[str]) -> tuple[int, str, str]:
            assert "-renderproject" in argv
            return 0, "rendered", ""

    receipt = run_reaper_render(
        project=project,
        expected_output=output,
        reaper_binary="/opt/reaper/reaper",
        reaper_version="7.82",
        runner=Runner(),
        ffprobe=lambda _: {
            "duration": "1.000",
            "codec_name": "pcm_s24le",
            "sample_rate": "48000",
            "channels": 2,
        },
        now=lambda: datetime(2026, 10, 5, 18, 0, tzinfo=UTC),
    )
    assert receipt["schema"] == "MediaExecutionResult/v1"
    assert receipt["status"] == "PASS"
    assert receipt["input_project_sha256"] == hashlib.sha256(b"RPP").hexdigest()
    assert receipt["output_sha256"] == hashlib.sha256(b"RIFFfake-wave").hexdigest()
    assert receipt["audio"]["sample_rate"] == "48000"


def test_failed_reaper_render_never_returns_pass(tmp_path: Path) -> None:
    project = tmp_path / "bad.rpp"
    project.write_text("RPP", encoding="utf-8")

    class Runner:
        def __call__(self, argv: list[str]) -> tuple[int, str, str]:
            return 3, "", "render failed"

    with pytest.raises(RenderFailure, match="REAPER_RENDER_FAILED"):
        run_reaper_render(
            project=project,
            expected_output=tmp_path / "missing.wav",
            reaper_binary="/opt/reaper/reaper",
            reaper_version="7.82",
            runner=Runner(),
            ffprobe=lambda _: {},
        )


def test_driver_unavailable_is_blocked() -> None:
    with pytest.raises(DriverUnavailable, match="BLOCKED_DRIVER"):
        assert_gpu_driver({"returncode": 1, "stdout": "", "stderr": "no device"})


def test_nvenc_failure_is_blocked() -> None:
    with pytest.raises(NvencUnavailable, match="BLOCKED_NVENC"):
        assert_nvenc_encode(
            ffmpeg={"returncode": 1, "stderr": "unknown encoder"},
            ffprobe=None,
        )


def test_cross_project_access_must_be_denied() -> None:
    assert_cross_project_denied(
        own_project="hazewave",
        other_project="br-no-gta",
        access_result={"allowed": False, "error_code": "AccessDenied"},
    )
    with pytest.raises(CrossIsolationError, match="BLOCKED_ISOLATION"):
        assert_cross_project_denied(
            own_project="hazewave",
            other_project="br-no-gta",
            access_result={"allowed": True, "error_code": None},
        )


def test_persistence_receipt_requires_same_markers_after_restart(tmp_path: Path) -> None:
    from workstation_runtime.persistence import create_marker, verify_marker

    marker = tmp_path / "persistence.json"
    create_marker(
        marker,
        project="hazewave",
        reaper_version="7.82",
        project_sha256="abc123",
    )
    loaded = json.loads(marker.read_text(encoding="utf-8"))
    assert verify_marker(marker, expected=loaded) is True
    marker.write_text('{"project":"tampered"}', encoding="utf-8")
    assert verify_marker(marker, expected=loaded) is False
