from __future__ import annotations


class DriverUnavailable(RuntimeError):
    pass


class NvencUnavailable(RuntimeError):
    pass


class CrossIsolationError(RuntimeError):
    pass


def assert_gpu_driver(result: dict) -> None:
    if int(result.get("returncode", 1)) != 0:
        raise DriverUnavailable("BLOCKED_DRIVER")
    if "NVIDIA" not in str(result.get("stdout", "")).upper():
        raise DriverUnavailable("BLOCKED_DRIVER")


def assert_nvenc_encode(*, ffmpeg: dict, ffprobe: dict | None) -> None:
    if int(ffmpeg.get("returncode", 1)) != 0:
        raise NvencUnavailable("BLOCKED_NVENC")
    if not ffprobe:
        raise NvencUnavailable("BLOCKED_NVENC")
    codec = str(ffprobe.get("codec_name", "")).lower()
    if codec not in {"h264", "hevc", "av1"}:
        raise NvencUnavailable("BLOCKED_NVENC")


def assert_cross_project_denied(
    *,
    own_project: str,
    other_project: str,
    access_result: dict,
) -> None:
    if access_result.get("allowed") is True:
        raise CrossIsolationError("BLOCKED_ISOLATION")
    code = str(access_result.get("error_code") or "")
    if code not in {"AccessDenied", "403", "UnauthorizedOperation"}:
        raise CrossIsolationError("BLOCKED_ISOLATION:UNPROVEN_DENIAL")
