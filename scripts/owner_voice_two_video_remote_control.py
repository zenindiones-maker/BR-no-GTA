#!/usr/bin/env python3
"""BR_OWNER_V1 control-plane-only handoff to ONE existing GitHub Codespace.

This process runs locally only to query metadata and invoke SSH.
All git reads, model checks, ffmpeg, decoding and ASR run remotely under
owner_voice_two_video_codespace_run.py's independent fail-closed authorization.
Never create/restart a Codespace, infer locally, transfer media or retry blindly.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys

CODESPACE = "br-v23-recovery-gxp67g5g7wphwxjw"
REPO = "zenindiones-maker/BR-no-GTA"
BRANCH = "work/br-owner-voice-coherent-qa-recovery-v1"


class ControlBlocked(RuntimeError):
    pass


def find_authorized_target(entries):
    """Require the exact existing Codespace, repo ownership and running state."""
    if not isinstance(entries, list):
        raise ControlBlocked("TARGET_LIST_INVALID")
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("name") != CODESPACE:
            continue
        repository = entry.get("repository")
        if isinstance(repository, dict):
            repository = repository.get("fullName") or repository.get("nameWithOwner")
        if repository != REPO:
            raise ControlBlocked("TARGET_REPOSITORY_MISMATCH")
        state = entry.get("state")
        if state == "Shutdown":
            raise ControlBlocked(
                "TARGET_NOT_RUNNING_NO_AUTO_START_Shutdown; "
                "CHECK_FREE_QUOTA in GitHub Settings > Billing & Licensing; "
                "RESUME_EXISTING_MANUALLY at https://github.com/codespaces; "
                "then rerun this controller. No paid resources started."
            )
        if state not in ("Available", "Running"):
            raise ControlBlocked("TARGET_NOT_RUNNING_NO_AUTO_START_" + str(state))
        return CODESPACE
    raise ControlBlocked("TARGET_EXISTING_CODESPACE_NOT_FOUND")


def remote_script():
    """Pure fixed shell; never interpolate local paths, credentials or user input."""
    return r'''set -euo pipefail
if [[ "${CODESPACES:-}" != "true" ||
      "${CODESPACE_NAME:-}" != "br-v23-recovery-gxp67g5g7wphwxjw" ||
      "${GITHUB_REPOSITORY:-}" != "zenindiones-maker/BR-no-GTA" ]]; then
    echo "REMOTE_AUTHORIZATION=DENIED" >&2
    exit 3
fi
repo=""
for candidate in "${CODESPACE_VSCODE_FOLDER:-}" \
                 /workspaces/BR-no-GTA /workspaces/BR \
                 "$HOME/BR-no-GTA" "$HOME/BR" \
                 /home/codespace/BR-no-GTA /home/vscode/BR-no-GTA; do
    [[ -n "$candidate" ]] || continue
    if git -C "$candidate" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        repo="$(git -C "$candidate" rev-parse --show-toplevel)"
        break
    fi
done
if [[ -z "$repo" ]]; then
    echo "REMOTE_BR_REPOSITORY_NOT_FOUND" >&2
    exit 4
fi
cd "$repo"
git fetch --quiet --no-tags origin work/br-owner-voice-coherent-qa-recovery-v1
git show FETCH_HEAD:scripts/owner_voice_two_video_codespace_run.py | python3
'''


def main(env=None):
    env = os.environ if env is None else env
    if env.get("CODESPACES") == "true":
        raise ControlBlocked(
            "CONTROL_PLANE_ONLY: in Codespace call internal executor instead"
        )
    if not shutil.which("gh"):
        raise ControlBlocked("GH_CLI_MISSING_ON_CONTROL_TERMINAL")
    try:
        result = subprocess.run([
            "gh", "codespace", "list", "-R", REPO,
            "--json", "name,repository,state", "--limit", "100",
        ], capture_output=True, text=True, timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ControlBlocked("TARGET_DISCOVERY_UNAVAILABLE") from exc
    if result.returncode:
        raise ControlBlocked("TARGET_DISCOVERY_FAILED_CHECK_GH_AUTH_AND_CODESPACE")
    try:
        available = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise ControlBlocked("TARGET_DISCOVERY_INVALID_JSON") from exc
    target = find_authorized_target(available)
    command = "bash -lc " + shlex.quote(remote_script())
    print("REMOTE_CONTROL_TARGET=" + target, flush=True)
    print("REMOTE_CONTROL_REPOSITORY=" + REPO, flush=True)
    print("A15_INFERENCE=FORBIDDEN", flush=True)
    print("SSH_HANDOFF=START", flush=True)
    try:
        ssh = subprocess.run([
            "gh", "codespace", "ssh", "-c", target, "--", command,
        ], check=False)
    except OSError as exc:
        raise ControlBlocked("REMOTE_CODESPACE_SSH_UNAVAILABLE") from exc
    if ssh.returncode:
        raise ControlBlocked("REMOTE_CODESPACE_SSH_FAILED_EXIT_" + str(ssh.returncode))
    print("SSH_HANDOFF=COMPLETE_CHECK_REMOTE_ASR_RECEIPT", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ControlBlocked as exc:
        print("OWNER_VOICE_REMOTE_CONTROL=FAIL " + str(exc), file=sys.stderr)
        sys.exit(2)
