"""Export an unvalidated code patch, never the runner or authentication home."""
import argparse
import difflib
import json
import os
from pathlib import Path
import re
import subprocess


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL)


def export(root, destination, base):
    base = git(root, "rev-parse", "--verify", base + "^{commit}").decode().strip()
    paths = set(git(root, "diff", "--name-only", "-z", base).decode().split("\0"))
    paths.update(git(root, "ls-files", "--others", "--exclude-standard", "-z").decode().split("\0"))
    chunks = []
    omitted = 0
    secrets = [v for k, v in os.environ.items()
               if re.search(r"token|secret|password|api_key", k, re.I) and len(v) >= 8]
    for name in sorted(paths - {""}):
        path = Path(name)
        if not (name.startswith("app/services/") or name.startswith("tests/")) or path.suffix != ".py" or any(p.startswith(".") for p in path.parts):
            omitted += 1
            continue
        target = root / path
        if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
            omitted += 1
            continue
        try:
            old = git(root, "show", f"{base}:{name}").decode()
        except subprocess.CalledProcessError:
            old = ""
        new = target.read_text() if target.is_file() else ""
        text = old + new
        if any(value in text for value in secrets) or re.search(
            r"ghp_|github_pat_|sk-[A-Za-z0-9]{16}|-----BEGIN .*PRIVATE KEY|"
            r"(?:access_token|refresh_token|user_code)\s*[=:]\s*['\"][^'\"]+['\"]", text):
            omitted += 1
            continue
        diff = difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                      fromfile="a/" + name if old else "/dev/null",
                      tofile="b/" + name if target.exists() else "/dev/null")
        for line in diff:
            chunks.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "partial.patch").write_text("".join(chunks))
    (destination / "recovery.json").write_text(json.dumps({
        "base_commit": base, "status": "UNVALIDATED_RECOVERY_ONLY",
        "omitted_paths": omitted, "automatic_commit": False,
    }, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export(Path.cwd(), args.output, args.base)
