"""Live ARTEX Git-archive provenance probe.

Fetch pinned public source into a disposable CI directory, never execute any
upstream shell, Go, JS, Docker, installer, or agent code.  This is a real
content-equivalence check, not a BR Harness or ARTEX runtime E2E.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path, PurePosixPath
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "br_artex_source_quarantine", ROOT / "scripts/br_artex_source_quarantine.py"
)
assert SPEC and SPEC.loader
artex = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(artex)


class ArtexLiveArchiveEvidence(unittest.TestCase):
    def test_pinned_upstream_git_archive_matches_immutable_tree(self):
        with tempfile.TemporaryDirectory(prefix="br-artex-probe-") as temp:
            root = Path(temp)
            gitdir = root / "isolated-git"
            payload = root / "source"
            gitdir.mkdir(mode=0o700)
            payload.mkdir(mode=0o700)

            artex._git("init", "--quiet", cwd=gitdir)
            artex._git(
                "fetch", "--no-tags", "--depth", "1",
                artex.SOURCE, artex.REV, cwd=gitdir,
            )
            self.assertEqual(artex._git("rev-parse", "FETCH_HEAD", cwd=gitdir), artex.REV)
            self.assertEqual(
                artex._git("rev-parse", "FETCH_HEAD^{tree}", cwd=gitdir),
                artex.TREE,
            )

            archive = root / "payload.tar"
            with archive.open("wb") as stream:
                artex._git(
                    "archive", "--format=tar", "FETCH_HEAD",
                    cwd=gitdir, stdout=stream,
                )

            count = 0
            total = 0
            names: set[str] = set()
            with tarfile.open(archive, "r:") as bundle:
                for member in bundle:
                    name = PurePosixPath(member.name)
                    self.assertFalse(name.is_absolute())
                    self.assertNotIn("..", name.parts)
                    self.assertNotIn(".git", name.parts)
                    if member.isdir():
                        continue
                    self.assertTrue(member.isfile(), "archive contains non-regular file")
                    self.assertNotIn(name.as_posix(), names)
                    names.add(name.as_posix())
                    count += 1
                    total += member.size
                    self.assertLessEqual(count, artex.MAX_FILES)
                    self.assertLessEqual(total, artex.MAX_BYTES)
                    target = payload.joinpath(*name.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = bundle.extractfile(member)
                    self.assertIsNotNone(source)
                    with source, target.open("xb") as output:
                        remaining = member.size
                        while remaining:
                            block = source.read(min(1024 * 1024, remaining))
                            self.assertTrue(block, "truncated archive entry")
                            output.write(block)
                            remaining -= len(block)

            self.assertTrue((payload / "go.mod").is_file())
            self.assertTrue((payload / ".gitattributes").is_file())
            self.assertIn(
                b"*.bat text eol=crlf",
                (payload / ".gitattributes").read_bytes(),
            )
            self.assertEqual(artex._git_tree_oid(payload), artex.TREE)
            print("ARTEX_PINNED_ARCHIVE_REAL_TREE=PASS")
            print("ARTEX_RUNTIME=NOT_INSTALLED")
            print("ARTEX_HARNESS_BINDING=NONE")


if __name__ == "__main__":
    unittest.main()
