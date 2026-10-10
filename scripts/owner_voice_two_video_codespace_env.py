#!/usr/bin/env python3
"""Private, Codespace-only recovery of the Whisper/CTranslate2 Python runtime.

Diagnostics first: reuse any healthy interpreter. Only then create a small,
isolated venv in the SAME Codespace, never A15/Termux or the repository.
Single wheel-only install; no machine creation, model cloning, or voice edits.
"""
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

AUTHORIZED_CODESPACE = "br-v23-recovery-gxp67g5g7wphwxjw"
AUTHORIZED_REPO = "zenindiones-maker/BR-no-GTA"
PINNED_DEPENDENCIES = (
    "numpy==2.2.6",
    "av==18.0.0",
    "ctranslate2==4.8.2",
    "faster-whisper==1.2.1",
)
MODULES = ("numpy", "av", "ctranslate2", "faster_whisper")
PROBE = (
    "import importlib,sys;"
    "mods=('numpy','av','ctranslate2','faster_whisper');"
    "[(importlib.import_module(m)) for m in mods];"
    "print('HEALTHY_ASR_RUNTIME')"
)


class EnvironmentBlocked(RuntimeError):
    pass


def authorize(env):
    if not (env.get("CODESPACES") == "true"
            and env.get("CODESPACE_NAME") == AUTHORIZED_CODESPACE
            and env.get("GITHUB_REPOSITORY") == AUTHORIZED_REPO):
        raise EnvironmentBlocked("AUTHORIZATION_DENIED_CODESPACE_ONLY")


def candidate_python_paths(root, env):
    """Explore a small fixed list; no recursive search, arbitrary execution, or logs."""
    home = Path.home()
    locations = [
        env.get("BR_OWNER_PYTHON"),
        str(Path(env["VIRTUAL_ENV"]) / "bin/python")
        if env.get("VIRTUAL_ENV") else None,
        str(root / "owner-voice-acoustic-execution/.asr-venv/bin/python"),
        str(root / "owner-voice-dubbing-input/.venv/bin/python"),
        str(root / "owner-voice-dubbing/.venv/bin/python"),
        str(root / ".venv/bin/python"),
        str(home / ".venv/bin/python"),
        str(home / "venv/bin/python"),
        str(home / ".local/share/venvs/owner-voice/bin/python"),
        "/workspaces/BR-no-GTA/.venv/bin/python",
        "/workspaces/BR/.venv/bin/python",
        "/opt/venv/bin/python",
        sys.executable,
        shutil.which("python3.12"),
        shutil.which("python3.11"),
        shutil.which("python3.13"),
        shutil.which("python3"),
    ]
    return list(dict.fromkeys(str(v) for v in locations if v))


def probe_python(candidate):
    """Report *module name*, not exception stack/credentials/other private state."""
    diagnostic = (
        "import importlib,sys;"
        "modules=('numpy','av','ctranslate2','faster_whisper');"
        "\nfor name in modules:\n"
        " try: importlib.import_module(name)\n"
        " except Exception: print('MISSING:'+name); sys.exit(3)\n"
        "print('HEALTHY_ASR_RUNTIME')"
    )
    try:
        result = subprocess.run(
            [str(candidate), "-c", diagnostic],
            capture_output=True, text=True, timeout=45, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "UNAVAILABLE", "python": str(candidate)}
    raw = result.stdout.strip().splitlines()
    status = raw[-1].strip() if raw else "IMPORT_ERROR"
    if result.returncode == 0 and status == "HEALTHY_ASR_RUNTIME":
        status = "PASS"
    elif not status.startswith("MISSING:"):
        status = "IMPORT_ERROR"
    return {"status": status, "python": str(candidate)}


def select_base_python():
    """Prefer CPython with native binary Linux wheels; never use phone Python 3.14."""
    for base in ("python3.12", "python3.11", "python3.13"):
        exe = shutil.which(base)
        if exe is None:
            continue
        try:
            check = subprocess.run(
                [exe, "-c",
                 "import platform,sys; assert sys.version_info[:2] in "
                 "((3, 11),(3, 12),(3, 13)); "
                 "assert platform.system()=='Linux'"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=15, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if check.returncode == 0:
            return exe
    raise EnvironmentBlocked("NO_SUPPORTED_CODESPACE_PYTHON_3_11_TO_3_13")


def bootstrap_private_venv(root):
    """One wheel-only install to private venv; no repo changes or global pip."""
    base = select_base_python()
    root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root.parent, 0o700)
    if shutil.disk_usage(root.parent).free < 1024 * 1024 * 1024:
        raise EnvironmentBlocked("INSUFFICIENT_CODESPACE_DISK_FOR_ASR")
    executable = root / "bin/python"
    if not executable.is_file():
        try:
            result = subprocess.run(
                [base, "-m", "venv", str(root)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
                text=True, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EnvironmentBlocked("PRIVATE_VENV_CREATION_FAILED") from exc
        if result.returncode:
            raise EnvironmentBlocked("PRIVATE_VENV_CREATION_FAILED")
    print("PRIVATE_CODESPACE_ASR_BOOTSTRAP=START", flush=True)
    args = [
        str(executable), "-m", "pip", "install",
        "--disable-pip-version-check", "--no-input",
        "--only-binary=:all:", *PINNED_DEPENDENCIES,
    ]
    try:
        installed = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=900, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EnvironmentBlocked("BINARY_WHEEL_INSTALL_FAILED_OR_TIMED_OUT") from exc
    if installed.returncode:
        # Avoid echoing pip text which can contain auth indexes/credentials.
        raise EnvironmentBlocked("BINARY_WHEEL_INSTALL_FAILED_CHECK_WHEELS_OR_NETWORK")
    checked = probe_python(str(executable))
    if checked["status"] != "PASS":
        raise EnvironmentBlocked(
            "BOOTSTRAP_IMPORT_FAILURE_" + checked["status"].replace(":", "_")
        )
    print("PRIVATE_CODESPACE_ASR_BOOTSTRAP=PASS", flush=True)
    return str(executable)


def ensure_python(root, env):
    """Reuse environment, then explicitly prepare one private venv if needed."""
    checked = []
    for candidate in candidate_python_paths(root, env):
        result = probe_python(candidate)
        checked.append(result)
        if result["status"] == "PASS":
            print("EXISTING_ASR_PYTHON=PASS", flush=True)
            return str(candidate)
    summary = ",".join(x["status"] for x in checked[:12])
    print("EXISTING_ASR_PYTHON=NOT_FOUND diagnostics=" +
          (summary or "NO_CANDIDATES"), flush=True)
    return bootstrap_private_venv(
        root / "owner-voice-acoustic-execution" / ".asr-venv"
    )


def main():
    authorize(os.environ)
    root = Path.home() / ".local/share/br-no-gta"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    selected = ensure_python(root, os.environ)
    if probe_python(selected)["status"] != "PASS":
        raise EnvironmentBlocked("FINAL_ASR_RUNTIME_NOT_HEALTHY")
    print("ASR_REMOTE_PYTHON_READY=PASS", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EnvironmentBlocked, OSError) as exc:
        print("ASR_CODESPACE_ENV=FAIL " + str(exc)[:150], file=sys.stderr)
        sys.exit(2)
