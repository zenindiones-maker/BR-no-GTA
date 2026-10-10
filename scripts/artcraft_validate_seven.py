#!/usr/bin/env python3
"""Read-only study harness for seven pinned ArtCraft Rust workspaces.

Runs each upstream project's build/test inside an unprivileged disposable Docker
container with --network none, no GitHub token, cap drop, and no deployment mounts.
Dependency resolution occurs separately via 'cargo fetch' (no upstream scripts).
Never imports upstream Python, runs source setup scripts or clones submodules.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time
import tomllib
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/research/artcraft-seven-pinned-sources.json"
RUST_IMAGE = "rust:1.95-slim-bookworm"
PROJECTS = {"photocraft", "vectorcraft", "filmcraft", "lightcraft", "pdfcraft", "effectcraft", "designcraft"}


def run_command(args: list[str], *, cwd: Path | None, log: Path, timeout: int,
                env: dict[str, str] | None = None) -> dict[str, Any]:
    """Run exact argv only. Bound time and log size; never shell=True."""
    start = time.monotonic()
    code: int | None = None
    status = "failed"
    with log.open("w", encoding="utf-8") as fp:
        fp.write("$ " + " ".join(args) + "\n")
        fp.flush()
        try:
            proc = subprocess.run(
                args, cwd=cwd, stdout=fp, stderr=subprocess.STDOUT,
                timeout=timeout, check=False, env=env,
            )
            code = proc.returncode
            status = "success" if code == 0 else "failed"
        except subprocess.TimeoutExpired:
            status = "timeout"
        except OSError as exc:
            status = "unavailable"
            fp.write(f"\nEXECUTION_UNAVAILABLE={exc!r}\n")
    text = log.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    return {
        "status": status, "exit_code": code,
        "duration_seconds": round(time.monotonic() - start, 2),
        "last_log_lines": lines[-35:],
        "log_file": log.name,
    }


def check_license(src: Path) -> str:
    candidates = sorted(
        (p for p in src.iterdir() if p.is_file() and
         (p.name.lower().startswith("license") or p.name.lower().startswith("copying"))),
        key=lambda p: p.name,
    )
    if not candidates:
        raise RuntimeError("UPSTREAM_LICENSE_NOT_FOUND")
    for lic in candidates:
        if "Apache License" in lic.read_text(encoding="utf-8", errors="replace"):
            return lic.name
    raise RuntimeError("UPSTREAM_APACHE_LICENSE_NOT_VERIFIED")


def docker_args(*, src: Path, cargo: Path, target: Path, project: str,
                stage: str, network: str) -> list[str]:
    # Don't inherit host credentials, SSH keys, host docker socket, BR sources,
    # owner voice, webhooks or GitHub Actions runtime token.
    uid = os.getuid()
    gid = os.getgid()
    args = [
        "docker", "run", "--rm", "--name", f"artcraft-{project}-{stage}-{os.getpid()}",
        "--network", network, "--user", f"{uid}:{gid}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "256", "--memory", "5g", "--cpus", "2",
        "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=512m",
        "-e", "HOME=/tmp", "-e", "CARGO_HOME=/cargo",
        "-e", "CARGO_TARGET_DIR=/target", "-e", "CARGO_INCREMENTAL=0",
        "-e", "RUST_BACKTRACE=1",
        "-v", f"{src}:/src:ro",
        "-v", f"{cargo}:/cargo:{'rw' if stage == 'fetch' else 'ro'}",
        "-v", f"{target}:/target:rw",
        "-w", "/src", RUST_IMAGE,
    ]
    if network == "none":
        args.extend(["-e", "CARGO_NET_OFFLINE=true"])
    return args


def safe_tar_github(repo: Path, sha: str, destination: Path, log: Path) -> dict[str, Any]:
    dest = destination.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest.parent / "source.tar"
    with archive.open("wb") as fp:
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo),
             "archive", "--format=tar", sha],
            stdout=fp, check=True, timeout=90,
        )
    # Reject absolute paths, traversal, symlinks and devices even in trusted public source.
    with tarfile.open(archive, "r") as tf:
        for member in tf.getmembers():
            resolved = (dest / member.name).resolve()
            if not resolved.is_relative_to(dest):
                raise RuntimeError("SOURCE_TAR_TRAVERSAL")
            if not (member.isfile() or member.isdir()):
                raise RuntimeError("SOURCE_TAR_UNSAFE_ENTRY:" + member.name)
        tf.extractall(dest, filter="data")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    count = sum(1 for item in dest.rglob("*") if item.is_file())
    archive.unlink()
    log.write_text(f"ARCHIVED_EXACT_SOURCE={sha}\nTRACKED_EXTRACTED_FILES={count}\nSOURCE_TAR_SHA256={digest}\n",
                   encoding="utf-8")
    return {"files": count, "tar_sha256": digest}


def inventory(src: Path, project: str) -> dict[str, Any]:
    root = tomllib.loads((src / "Cargo.toml").read_text(encoding="utf-8"))
    ws = root.get("workspace", {})
    pkg = ws.get("package", {})
    members = sorted(str(x.relative_to(src)) for x in src.glob("crates/*/Cargo.toml"))
    apps = sorted(str(x.relative_to(src)) for x in src.glob("apps/*/Cargo.toml"))
    deps = ws.get("dependencies", {})
    external = {k: v for k, v in deps.items() if not (isinstance(v, dict) and "path" in v)}
    git_deps = {k: v for k, v in deps.items() if isinstance(v, dict) and "git" in v}
    lock = src / "Cargo.lock"
    # Avoid upload of any private-looking value from untrusted source configs.
    return {
        "edition": pkg.get("edition"),
        "minimum_rust": pkg.get("rust-version"),
        "workspace_crates": len(members), "workspace_apps": len(apps),
        "workspace_crate_names": [Path(p).parent.name for p in members],
        "workspace_app_names": [Path(p).parent.name for p in apps],
        "external_workspace_dependencies": len(external),
        "pinned_git_dependencies": {k: {"git": v.get("git"), "rev": v.get("rev")}
                                    for k, v in git_deps.items()},
        "cargo_lock_present": lock.exists(),
        "cargo_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None,
        "cli_manifest_present": (src / "apps" / f"{project}-cli" / "Cargo.toml").is_file(),
        "upstream_license_file": check_license(src),
        "major_modules": [Path(p).parent.name for p in members],
        "note": "Inventory derived from Cargo.toml and source at exact pinned SHA; not a feature parity proof",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", choices=sorted(PROJECTS), required=True)
    parser.add_argument("--output", default="artcraft-validation")
    args = parser.parse_args()
    project = args.project
    out = (ROOT / args.output / project).resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema"] == "BRArtCraftPinnedSourceStudy/v1"
    entries = manifest["projects"]
    assert len(entries) == 7 and {x["name"] for x in entries} == PROJECTS
    record = next(x for x in entries if x["name"] == project)
    sha = record["commit_sha"]
    assert re.fullmatch(r"[0-9a-f]{40}", sha)
    assert record["repository"] == "storytold/" + project
    assert record["clone_url"] == f"https://github.com/storytold/{project}.git"
    assert record["license"] == "Apache-2.0"

    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    report: dict[str, Any] = {
        "schema": "BRArtCraftRuntimeValidation/v1",
        "project": project, "repository": record["repository"],
        "pinned_sha": sha, "date_utc": stamp,
        "runtime_isolation": "Docker none networking for check/tests/build/help",
        "build_status": "not_attempted", "tests_status": "not_attempted",
        "cli_status": "not_attempted", "stages": {},
        "application_fully_installed": False,
        "gui_verified": False, "gpu_verified": False,
        "source_code_modified": False,
        "production_deployment": False,
        "owner_voice_or_telegram_access": False,
    }
    report_path = out / "result.json"

    def save() -> None:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save()
    temp = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / f"br-artcraft-{project}"
    gitrepo, src, cargo, target = (temp / x for x in ("gitrepo", "source", "cargo", "target"))
    for folder in (gitrepo, src, cargo, target):
        folder.mkdir(parents=True, exist_ok=True)
    try:
        fetch_env = {k: v for k, v in os.environ.items()
                     if k not in {"GITHUB_TOKEN", "GH_TOKEN", "ACTIONS_RUNTIME_TOKEN",
                                  "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "SSH_AUTH_SOCK", "GIT_ASKPASS"}}
        fetch_env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1",
                          "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"})
        for name, command in [
            ("git_init", ["git", "init", "--quiet", str(gitrepo)]),
            ("git_remote", ["git", "-C", str(gitrepo), "remote", "add", "origin", record["clone_url"]]),
            ("git_fetch", ["git", "-c", "core.hooksPath=/dev/null", "-C", str(gitrepo),
                           "fetch", "--no-tags", "--depth=1", "origin", sha]),
        ]:
            result = run_command(command, cwd=ROOT, log=out / f"{name}.log",
                                 timeout=210, env=fetch_env)
            report["stages"][name] = result
            save()
            if result["status"] != "success":
                raise RuntimeError("SOURCE_FETCH_FAILED:" + name)
        observed = subprocess.check_output(
            ["git", "-C", str(gitrepo), "rev-parse", "FETCH_HEAD"], text=True,
            timeout=15, env=fetch_env).strip()
        if observed != sha:
            raise RuntimeError("SOURCE_SHA_MISMATCH")
        report["source"] = safe_tar_github(gitrepo, sha, src, out / "archive.log")
        report["source"]["sha_verified"] = True
        report["inventory"] = inventory(src, project)
        report["source_status"] = "verified"
        save()

        # Docker image is downloaded before running source code, no input secrets.
        preflight = run_command(["docker", "pull", RUST_IMAGE], cwd=ROOT,
                                log=out / "docker_pull.log", timeout=360)
        report["stages"]["docker_pull"] = preflight
        save()
        if preflight["status"] != "success":
            raise RuntimeError("RUST_SANDBOX_IMAGE_UNAVAILABLE")
        image_inspect = run_command(
            ["docker", "image", "inspect", RUST_IMAGE, "--format", "{{json .RepoDigests}}"],
            cwd=ROOT, log=out / "docker_image_digest.log", timeout=20)
        report["stages"]["image_inspect"] = image_inspect
        save()

        if not report["inventory"]["cargo_lock_present"]:
            report["dependency_status"] = "blocked_missing_cargo_lock"
            save()
            raise RuntimeError("LOCKFILE_REQUIRED_FOR_REPRODUCIBLE_CHECK")

        fetch = docker_args(src=src, cargo=cargo, target=target, project=project,
                            stage="fetch", network="bridge") + ["cargo", "fetch", "--locked"]
        stage = run_command(fetch, cwd=ROOT, log=out / "cargo_fetch.log", timeout=300)
        report["stages"]["cargo_fetch"] = stage
        report["dependency_status"] = "fetched" if stage["status"] == "success" else stage["status"]
        save()
        if stage["status"] != "success":
            raise RuntimeError("LOCKED_DEPENDENCY_FETCH_FAILED")
        # All source execution (including Rust build scripts and proc macros) is
        # confined to a Docker container with NO network interface and NO secrets.
        offline = docker_args(src=src, cargo=cargo, target=target, project=project,
                              stage="check", network="none")
        check = run_command(offline + ["cargo", "check", "--workspace", "--locked", "--offline"],
                            cwd=ROOT, log=out / "cargo_check.log", timeout=510)
        report["stages"]["cargo_check"] = check
        report["build_status"] = check["status"]
        save()

        candidate_core = f"{project}-time" if project in {"filmcraft", "effectcraft"} else f"{project}-geom"
        core = docker_args(src=src, cargo=cargo, target=target, project=project,
                           stage="core-test", network="none")
        test = run_command(core + ["cargo", "test", "--locked", "--offline",
                                   "-p", candidate_core, "--lib"],
                           cwd=ROOT, log=out / "core_test.log", timeout=210)
        report["stages"]["core_test"] = test
        report["core_crate"] = candidate_core
        report["tests_status"] = test["status"]
        save()

        if report["inventory"]["cli_manifest_present"] and check["status"] == "success":
            cli = f"{project}-cli"
            build = docker_args(src=src, cargo=cargo, target=target,
                                project=project, stage="cli-build", network="none")
            result = run_command(build + ["cargo", "build", "--locked", "--offline",
                                          "-p", cli], cwd=ROOT, log=out / "cli_build.log",
                                 timeout=300)
            report["stages"]["cli_build"] = result
            report["cli_status"] = result["status"]
            save()
            candidate = target / "debug" / cli
            if result["status"] == "success" and candidate.is_file():
                binary_bytes = candidate.stat().st_size
                if binary_bytes <= 50_000_000:
                    safe_binary = out / cli
                    shutil.copyfile(candidate, safe_binary)
                    safe_binary.chmod(0o644)  # never executable in downloadable report
                    report["compiled_artifact"] = {
                        "filename": cli, "bytes": binary_bytes,
                        "sha256": hashlib.sha256(safe_binary.read_bytes()).hexdigest(),
                        "not_executed_on_host": True,
                    }
                probe = docker_args(src=src, cargo=cargo, target=target,
                                    project=project, stage="cli-smoke", network="none")
                result = run_command(probe + [f"/target/debug/{cli}", "--help"],
                                     cwd=ROOT, log=out / "cli_help.log", timeout=18)
                report["stages"]["cli_help"] = result
                report["cli_smoke_status"] = result["status"]
                save()
        else:
            report["cli_status"] = ("not_present" if not report["inventory"]["cli_manifest_present"]
                                    else "blocked_by_workspace_check")
        report["assessment"] = (
            "CLI built/tested in network-disabled temporary container; GUI/GPU unverified"
            if report["stages"].get("cli_build", {}).get("status") == "success"
            else "Source/dependency/check/core-test attempted; see per-stage logs. GUI/GPU unverified"
        )
        save()
    except Exception as exc:
        report["blocking_error"] = str(exc)
        report["assessment"] = "Partial evidence only; do not claim installed or functioning"
        save()
    finally:
        # Ensure no detached Docker container survives a step timeout.
        try:
            names = subprocess.check_output(
                ["docker", "ps", "-aq", "--filter", f"name=artcraft-{project}-"],
                text=True, timeout=15).split()
            if names:
                subprocess.run(["docker", "rm", "-f", *names], check=False, timeout=30)
        except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
            pass
    print(f"PROJECT={project} SHA={sha} SOURCE={report.get('source_status', 'unavailable')}")
    print(f"DEPENDENCIES={report.get('dependency_status', 'not_attempted')}")
    print(f"WORKSPACE_CHECK={report['build_status']} CORE_TEST={report['tests_status']}")
    print(f"CLI_BUILD={report['cli_status']} GUI=UNVERIFIED GPU=UNVERIFIED")
    if report.get("blocking_error"):
        print("BLOCKER=" + report["blocking_error"])
    print("EVIDENCE=" + str(report_path.relative_to(ROOT)))
    # Upload evidence with if: always() in workflow, while preserving a truthful
    # red check for a failed build/test/CLI smoke. Never promote partial success.
    accepted = (
        report["build_status"] == "success"
        and report["tests_status"] == "success"
        and report["cli_status"] in {"success", "not_present"}
        and report.get("cli_smoke_status", "success") == "success"
    )
    print("ARTCRAFT_ISOLATED_TECHNICAL_GATE=" + ("PASS" if accepted else "FAIL"))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
