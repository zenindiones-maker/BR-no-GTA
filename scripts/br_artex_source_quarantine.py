#!/usr/bin/env python3
"""Stage the pinned ARTEX source for offline security research, without executing it.

This script is NOT an ARTEX runtime installer. All external code remains inert.
The destination is outside BR-no-GTA's Git checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile

SOURCE = "https://github.com/Hinln/ARTEX.git"
REV = "f3e3f54b6c93916388a0a3dc6a439893a9abe37a"
TREE = "1c1776fea9e1f43810cb40873932a5f42c202482"
CODESPACE = "br-v23-recovery-gxp67g5g7wphwxjw"
MAX_FILES = 15000
MAX_BYTES = 150 * 1024 * 1024
DEST_NAME = "artex-0.3.15-" + REV[:12]
RECEIPT = ".br_artex_source_receipt.json"
# Executable entries observed in the independently pinned upstream Git tree.
# Staging v1 intentionally discarded mode bits, so mode is reconstructed
# strictly from this allowlist for backward-compatible content verification.
SOURCE_EXECUTABLES = frozenset({
    "build.sh", "dev.sh", "install.sh", "reset-password.sh",
    "start.sh", "update.sh",
})


class Blocked(RuntimeError):
    pass


def _git(*args: str, cwd: Path | None = None, stdout=None) -> str:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_LFS_SKIP_SMUDGE": "1",
    }
    try:
        result = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", *args],
            cwd=cwd, env=env, stdout=stdout or subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=180, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Blocked("Git unavailable or timed out") from exc
    if result.returncode:
        raise Blocked("Git operation failed (no automatic retry)")
    if stdout:
        return ""
    return result.stdout.decode("utf-8", "strict").strip()


def _guard() -> Path:
    if os.environ.get("CODESPACES", "").lower() != "true":
        raise Blocked("requires an existing GitHub Codespace")
    if os.environ.get("CODESPACE_NAME") != CODESPACE:
        raise Blocked("wrong Codespace; do not create or switch machines")
    root = Path(_git("rev-parse", "--show-toplevel")).resolve()
    origin = _git("remote", "get-url", "origin", cwd=root)
    allowed = (
        "https://github.com/zenindiones-maker/BR-no-GTA",
        "git@github.com:zenindiones-maker/BR-no-GTA",
        "ssh://git@github.com/zenindiones-maker/BR-no-GTA",
    )
    if not any(origin == item or origin == item + ".git" for item in allowed):
        raise Blocked("not the authorized BR-no-GTA repository")
    if not (root / "AGENTS.md").is_file():
        raise Blocked("repository policy missing")
    return root


def _destination() -> Path:
    home = Path.home().resolve()
    dest = home / ".local/share/br-no-gta/external-source-quarantine" / DEST_NAME
    if any(path.is_symlink() for path in (dest, *dest.parents) if path != home and home in path.parents):
        raise Blocked("source destination traverses a symlink")
    return dest


def _manifest(directory: Path) -> tuple[int, int, str]:
    entries = []
    size = 0
    for path in sorted(directory.rglob("*")):
        if path.relative_to(directory).as_posix() == RECEIPT:
            continue
        if path.is_symlink():
            raise Blocked("symlink in staged source")
        if not path.is_file():
            continue
        relative = path.relative_to(directory).as_posix()
        content = path.read_bytes()
        size += len(content)
        if size > MAX_BYTES or len(entries) >= MAX_FILES:
            raise Blocked("source exceeds limits")
        entries.append(relative + "\t" + hashlib.sha256(content).hexdigest() + "\n")
    return len(entries), size, hashlib.sha256("".join(entries).encode()).hexdigest()



def _git_tree_oid(directory: Path) -> str:
    """Recompute the Git tree object ID from the actual staged source bytes.

    The receipt is excluded, but every other file and directory is included.
    Reconstruct known upstream executable modes instead of relying on the
    permission bits lost by the older inert-source staging procedure.
    """

    def walk(current: Path) -> bytes:
        entries: list[tuple[bytes, bytes]] = []
        for path in current.iterdir():
            if path == directory / RECEIPT:
                continue
            if path.is_symlink():
                raise Blocked("symlink in staged source")
            name = os.fsencode(path.name)
            if path.is_dir():
                mode = b"40000"
                oid = walk(path)
                order_key = name + b"/"
            elif path.is_file():
                relative = path.relative_to(directory).as_posix()
                if path.stat().st_mode & 0o111 and relative not in SOURCE_EXECUTABLES:
                    raise Blocked("unexpected executable source file")
                mode = b"100755" if relative in SOURCE_EXECUTABLES else b"100644"
                raw = path.read_bytes()
                # Pinned upstream .gitattributes sets '*.bat text eol=crlf'.
                # 'git archive' exports CRLF while the committed Git blob
                # is LF-normalized. Reverse that single declared conversion
                # before comparing the reconstructed tree to the pinned SHA.
                if relative.endswith(".bat"):
                    raw = raw.replace(b"\r\n", b"\n")
                header = b"blob " + str(len(raw)).encode("ascii") + b"\x00"
                oid = hashlib.sha1(header + raw).digest()
                order_key = name
            else:
                raise Blocked("unsupported file type in staged source")
            entries.append((order_key, mode + b" " + name + b"\x00" + oid))
        entries.sort(key=lambda entry: entry[0])
        raw_tree = b"".join(entry[1] for entry in entries)
        header = b"tree " + str(len(raw_tree)).encode("ascii") + b"\x00"
        return hashlib.sha1(header + raw_tree).digest()

    return walk(directory).hex()


def _verify(dest: Path) -> None:
    if dest.is_symlink() or not dest.is_dir():
        raise Blocked("source directory missing or unsafe")
    try:
        data = json.loads((dest / RECEIPT).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Blocked("source receipt missing or invalid") from exc
    if (data.get("repository"), data.get("commit"), data.get("tree")) != (SOURCE, REV, TREE):
        raise Blocked("source pin mismatch")
    if data.get("runtime_enabled") is not False:
        raise Blocked("runtime must remain disabled")
    count, size, digest = _manifest(dest)
    if (count, size, digest) != (data.get("file_count"), data.get("byte_count"), data.get("manifest_sha256")):
        raise Blocked("staged source integrity mismatch")
    if _git_tree_oid(dest) != TREE:
        raise Blocked("source tree differs from pinned upstream Git tree")
    print("ARTEX_SOURCE_STAGING=PASS")
    print("ARTEX_SOURCE_COMMIT=" + REV)
    print("ARTEX_RUNTIME=NOT_INSTALLED")
    print("ARTEX_HARNESS_BINDING=NONE")


def _stage(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if dest.exists() or dest.is_symlink():
        _verify(dest)
        return
    with tempfile.TemporaryDirectory(prefix=".artex-research-", dir=dest.parent) as temp:
        work = Path(temp)
        git_dir = work / "git"
        payload = work / "source"
        git_dir.mkdir(mode=0o700)
        payload.mkdir(mode=0o700)
        _git("init", "--quiet", cwd=git_dir)
        _git("fetch", "--no-tags", "--depth", "1", SOURCE, REV, cwd=git_dir)
        if _git("rev-parse", "FETCH_HEAD", cwd=git_dir) != REV:
            raise Blocked("fetched source commit does not match")
        if _git("rev-parse", "FETCH_HEAD^{tree}", cwd=git_dir) != TREE:
            raise Blocked("fetched tree does not match")
        archive = work / "source.tar"
        with archive.open("wb") as stream:
            _git("archive", "--format=tar", "FETCH_HEAD", cwd=git_dir, stdout=stream)
        total = 0
        count = 0
        paths: set[str] = set()
        with tarfile.open(archive, "r:") as bundle:
            for member in bundle:
                name = PurePosixPath(member.name)
                if (name.is_absolute() or not name.parts
                        or any(p in ("..", ".git") for p in name.parts)):
                    raise Blocked("unsafe path in third-party archive")
                if member.isdir():
                    continue
                if not member.isfile() or member.size < 0:
                    raise Blocked("third-party archive contains unsafe file type")
                path = name.as_posix()
                if path in paths:
                    raise Blocked("duplicate source path")
                paths.add(path)
                count += 1
                total += member.size
                if count > MAX_FILES or total > MAX_BYTES:
                    raise Blocked("third-party source exceeds limits")
                target = payload.joinpath(*name.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                file_obj = bundle.extractfile(member)
                if file_obj is None:
                    raise Blocked("source archive entry unreadable")
                with file_obj, target.open("xb") as output:
                    remaining = member.size
                    while remaining:
                        block = file_obj.read(min(1024 * 1024, remaining))
                        if not block:
                            raise Blocked("truncated archive")
                        output.write(block)
                        remaining -= len(block)
        if not (payload / "go.mod").is_file() or not (payload / "LICENSE").is_file():
            raise Blocked("expected source package markers absent")
        if _git_tree_oid(payload) != TREE:
            raise Blocked("archive bytes do not match pinned Git tree")
        file_count, byte_count, digest = _manifest(payload)
        receipt = {
            "schema": "BRArtexInertSourceReceipt/v1",
            "repository": SOURCE,
            "commit": REV,
            "tree": TREE,
            "file_count": file_count,
            "byte_count": byte_count,
            "manifest_sha256": digest,
            "runtime_enabled": False,
            "security_review": "PENDING",
            "integration_review": "PENDING",
            "mode": "source-study-only",
        }
        (payload / RECEIPT).write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        payload.chmod(0o700)
        if dest.exists() or dest.is_symlink():
            raise Blocked("concurrent source installation detected")
        payload.rename(dest)
    _verify(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "verify"))
    args = parser.parse_args()
    try:
        _guard()
        dest = _destination()
        if args.action == "stage":
            _stage(dest)
        else:
            _verify(dest)
    except Blocked as exc:
        print("ARTEX_SOURCE_STAGING=BLOCKED: " + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
