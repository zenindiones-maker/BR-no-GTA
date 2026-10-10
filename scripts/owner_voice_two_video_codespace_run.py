#!/usr/bin/env python3
"""Execute owner-voice ASR only in the pre-existing BR-no-GTA Codespace.

No checkout changes, no new infrastructure, no model reinstall, no media
downloads, no public artifacts, no third-party voice conditioning.
"""
import fcntl
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile

AUTHORIZED_CODESPACE = "br-v23-recovery-gxp67g5g7wphwxjw"
AUTHORIZED_REPO = "zenindiones-maker/BR-no-GTA"
BRANCH = "work/br-owner-voice-coherent-qa-recovery-v1"
FILES = {
    "f8IZhKcuEts.mp4": "b4e981094e468a2ca5f5d270ff2a5338187df935a8d177971a2640bcc28f34be",
    "K6rVM6gn6k4.mp4": "ec4645c92e41be73a077f33f04159e45b9abc35c7843d5c7a35be7ccd75a1e52",
}


class LauncherBlocked(RuntimeError):
    pass


def authorize(env):
    if (env.get("CODESPACES") != "true"
            or env.get("CODESPACE_NAME") != AUTHORIZED_CODESPACE
            or env.get("GITHUB_REPOSITORY") != AUTHORIZED_REPO):
        raise LauncherBlocked("AUTHORIZATION=DENIED_EXISTING_CODESPACE_ONLY")


def git(repo, args, *, binary=False):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode:
        raise LauncherBlocked("GIT_OPERATION_FAILED_" + args[0].upper())
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def find_repository():
    root = git(Path.cwd(), ["rev-parse", "--show-toplevel"])
    repo = Path(root).resolve()
    remote = git(repo, ["remote", "get-url", "origin"])
    base = remote.removesuffix(".git")
    if not (base.endswith("github.com/" + AUTHORIZED_REPO)
            or base.endswith("github.com:" + AUTHORIZED_REPO)):
        raise LauncherBlocked("REPOSITORY_IDENTITY=DENIED")
    return repo


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_inputs(input_dir):
    for name, expected in FILES.items():
        path = input_dir / name
        if not path.is_file() or sha256_file(path) != expected:
            raise LauncherBlocked("INPUT_SHA256=FAILED_" + name)
    print("INPUT_SHA256_BOTH=PASS", flush=True)


def find_existing_python(repo, env):
    candidates = [
        env.get("BR_OWNER_PYTHON"),
        str(Path(env["VIRTUAL_ENV"]) / "bin/python")
        if env.get("VIRTUAL_ENV") else None,
        str(Path.home() / ".local/share/br-no-gta/owner-voice-acoustic-execution/.asr-venv/bin/python"),
        str(repo / ".venv/bin/python"),
        str(Path.home() / ".local/share/br-no-gta/owner-voice-dubbing/.venv/bin/python"),
        str(Path.home() / ".local/share/br-no-gta/.venv/bin/python"),
        str(Path.home() / ".local/share/venvs/owner-voice/bin/python"),
        str(Path.home() / "venv/bin/python"),
        str(Path.home() / ".venv/bin/python"),
        "/opt/venv/bin/python",
        "/workspaces/BR-no-GTA/.venv/bin/python",
        sys.executable,
        shutil.which("python3.12"),
        shutil.which("python3.11"),
        shutil.which("python3.13"),
        shutil.which("python3"),
    ]
    for candidate in dict.fromkeys(x for x in candidates if x):
        try:
            result = subprocess.run(
                [candidate, "-c", "import numpy, av, ctranslate2, faster_whisper"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            print("EXISTING_PYTHON_ENV=PASS", flush=True)
            return candidate
    raise LauncherBlocked(
        "PYTHON_ENV=BLOCKED_SET_BR_OWNER_PYTHON_TO_EXISTING_VENV"
    )


def atomic_private_bytes(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def verify_receipt(directory):
    run = json.loads((directory / "run-state.json").read_text("utf-8"))
    coverage = json.loads((directory / "coverage-quality.json").read_text("utf-8"))
    report = json.loads((directory / "candidate-report.json").read_text("utf-8"))
    if not (
        run.get("status") == "COMPLETE_ASR_UNVERIFIED"
        and run.get("videos_processed") == 2
        and len(coverage.get("videos", [])) == 2
        and len(report.get("videos", [])) == 2
        and coverage.get("unique_words", 0) > 0
        and coverage.get("total_occurrences", 0) > 0
        and coverage.get("acoustic_pronunciations_verified") == 0
        and all(v.get("total_occurrences", 0) > 0
                for v in coverage["videos"])
        and {v.get("video_id") for v in report["videos"]} ==
        {filename.removesuffix(".mp4") for filename in FILES}
        and all(report_item.get("media_sha256") == FILES[
            report_item["video_id"] + ".mp4"]
            for report_item in report["videos"])
        and report.get("speaker_reference_allowed") is False
        and report.get("runtime_activation") is False
    ):
        raise LauncherBlocked("REAL_TWO_VIDEO_RECEIPT=FAIL")
    print("REAL_TWO_VIDEO_ASR=PASS_UNVERIFIED", flush=True)
    print("UNIQUE_WORDS=" + str(coverage["unique_words"]), flush=True)
    print("TOTAL_OCCURRENCES=" + str(coverage["total_occurrences"]), flush=True)
    print("PRIVATE_REPORT_DIRECTORY=" + str(directory), flush=True)
    print("ACOUSTIC_REVIEW=PENDING", flush=True)
    print("RUNTIME_ACTIVATION=FORBIDDEN", flush=True)


def main():
    authorize(os.environ)  # No filesystem or network side effects before identity check.
    repo = find_repository()
    root = Path.home() / ".local/share/br-no-gta"
    input_dir = root / "owner-voice-dubbing-input"
    output_root = root / "owner-voice-acoustic-execution"
    output_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(output_root, 0o700)
    lock_path = output_root / ".exclusive.lock"
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LauncherBlocked("ACOUSTIC_RUN=BLOCKED_ALREADY_RUNNING") from exc
        verify_inputs(input_dir)
        python = find_existing_python(repo, os.environ)
        git(repo, ["fetch", "--quiet", "--no-tags", "origin", BRANCH])
        commit = git(repo, ["rev-parse", "--verify", "FETCH_HEAD"])
        if len(commit) != 40 or any(x not in "0123456789abcdef" for x in commit):
            raise LauncherBlocked("COMMIT_IDENTITY=INVALID")
        code = git(
            repo, ["show", commit + ":scripts/owner_voice_two_video_acoustic_probe.py"],
            binary=True,
        )
        if not code:
            raise LauncherBlocked("PINNED_ANALYZER=EMPTY")
        executable = output_root / "probe.py"
        atomic_private_bytes(executable, code)
        result = subprocess.run(
            [python, "-m", "py_compile", str(executable)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        if result.returncode:
            raise LauncherBlocked("PINNED_ANALYZER=INVALID_PYTHON")
        print("ANALYZER_COMMIT=" + commit, flush=True)
        target = output_root / "evidence"
        result = subprocess.run([
            python, str(executable),
            "--input-dir", str(input_dir), "--output", str(target),
            "--model", os.environ.get("BR_OWNER_ASR_MODEL", "small"),
        ], check=False)
        if result.returncode:
            raise LauncherBlocked("PRIVATE_ASR=FAILED_INSPECT_PRIVATE_RUN_STATE")
        verify_receipt(target)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (LauncherBlocked, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print("OWNER_VOICE_CODESPACE_RUN=FAIL " + str(exc)[:200],
              file=sys.stderr)
        sys.exit(2)
