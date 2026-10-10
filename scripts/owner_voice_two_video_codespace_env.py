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


def classify_venv_failure(stderr):
    """Reduce native Python creation errors to actionable, nonsecret codes."""
    msg = (stderr or "").lower()
    if "ensurepip is not available" in msg or "no module named ensurepip" in msg:
        return "ENSUREPIP_UNAVAILABLE"
    if "no module named venv" in msg:
        return "VENV_MODULE_MISSING"
    if "permission denied" in msg or "operation not permitted" in msg:
        return "PERMISSION_DENIED"
    if "no space left" in msg or "disk quota exceeded" in msg:
        return "NO_SPACE_LEFT"
    return "UNCLASSIFIED_VENV_ERROR"


def _pip_works(python):
    try:
        check = subprocess.run(
            [str(python), "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return check.returncode == 0


def bootstrap_private_venv(root):
    """Repair incomplete Ubuntu venv without deleting files or touching system Python.

    On Debian/Ubuntu, python -m venv may create bin/python but fail while
    invoking ensurepip. Resume its private state with --without-pip, then
    install wheels via existing uv or pip's documented --python option.
    Never build from source, install globally, or download a new Python.
    """
    base = select_base_python()
    root = Path(root)
    root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root.parent, 0o700)
    if shutil.disk_usage(root.parent).free < 1024 * 1024 * 1024:
        raise EnvironmentBlocked("INSUFFICIENT_CODESPACE_DISK_FOR_ASR")
    executable = root / "bin/python"
    if not executable.is_file():
        try:
            creation = subprocess.run(
                [base, "-m", "venv", str(root)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
                text=True, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EnvironmentBlocked("PRIVATE_VENV_CREATION_INTERRUPTED") from exc
        if creation.returncode:
            reason = classify_venv_failure(creation.stderr)
            print("PRIVATE_VENV_DIAGNOSIS=" + reason, flush=True)
            if reason != "ENSUREPIP_UNAVAILABLE":
                raise EnvironmentBlocked("PRIVATE_VENV_CREATION_FAILED_" + reason)
            # Debian/Ubuntu venv may be partially created. This modifies only
            # the dedicated private .asr-venv; never deletes prior checkpoints.
            try:
                recovery = subprocess.run(
                    [base, "-m", "venv", "--without-pip", str(root)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
                    text=True, check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise EnvironmentBlocked("PRIVATE_VENV_NO_PIP_RECOVERY_INTERRUPTED") from exc
            if recovery.returncode:
                raise EnvironmentBlocked(
                    "PRIVATE_VENV_NO_PIP_RECOVERY_FAILED_" +
                    classify_venv_failure(recovery.stderr)
                )
    if not executable.is_file():
        raise EnvironmentBlocked("PRIVATE_VENV_PYTHON_MISSING")

    if _pip_works(executable):
        method = "VENV_PIP"
        args = [
            str(executable), "-m", "pip", "install",
            "--disable-pip-version-check", "--no-input",
            "--only-binary=:all:", *PINNED_DEPENDENCIES,
        ]
    else:
        uv = shutil.which("uv")
        if uv:
            method = "EXISTING_UV"
            args = [
                uv, "pip", "install", "--python", str(executable),
                "--no-progress", "--no-python-downloads",
                "--only-binary", ":all:", *PINNED_DEPENDENCIES,
            ]
        else:
            # pip >=22.3 can install into venvs created --without-pip.
            drivers = list(dict.fromkeys([base, sys.executable]))
            driver = next((p for p in drivers if _pip_works(p)), None)
            if driver is None:
                raise EnvironmentBlocked(
                    "PRIVATE_VENV_NO_PIP_OR_UV: python3-venv/ensurepip "
                    "or an existing uv/pip bootstrap is required on the Codespace"
                )
            method = "HOST_PIP_PYTHON"
            args = [
                str(driver), "-m", "pip", "--python", str(root), "install",
                "--disable-pip-version-check", "--no-input",
                "--only-binary=:all:", *PINNED_DEPENDENCIES,
            ]
    print("PRIVATE_CODESPACE_ASR_INSTALL_METHOD=" + method, flush=True)
    try:
        installed = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=900, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EnvironmentBlocked("BINARY_WHEEL_INSTALL_INTERRUPTED") from exc
    if installed.returncode:
        # Never echo pip/uv stderr, indexes, tokens or private remote paths.
        raise EnvironmentBlocked(
            "BINARY_WHEEL_INSTALL_FAILED_" + method +
            "_CHECK_NETWORK_AND_AVAILABLE_WHEELS"
        )
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
