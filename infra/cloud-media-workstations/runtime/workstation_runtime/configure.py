from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
from pathlib import Path
import shlex
import tarfile


ANSIBLE_CORE_VERSION = "2.20.3"


class ConfigurationFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class BundleEvidence:
    path: Path
    sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_ansible_bundle(*, root: Path, output: Path) -> BundleEvidence:
    root = Path(root)
    ansible_root = root / "ansible"
    if not ansible_root.is_dir():
        raise ConfigurationFailed("ANSIBLE_ROOT_MISSING")

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in sorted(ansible_root.rglob("*")):
                    if any(part in {".git", ".terraform", "__pycache__"} for part in path.parts):
                        continue
                    relative = path.relative_to(root)
                    info = archive.gettarinfo(str(path), arcname=str(relative))
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.mtime = 0
                    if path.is_file():
                        with path.open("rb") as handle:
                            archive.addfile(info, handle)
                    else:
                        archive.addfile(info)

    return BundleEvidence(path=output, sha256=_sha256(output))


def _project_group(project: str) -> tuple[str, str]:
    if project == "hazewave":
        return "hazewave", "hazewave.yml"
    if project == "br-no-gta":
        return "br_no_gta", "br-no-gta.yml"
    raise ValueError("UNKNOWN_PROJECT")


def ssm_configuration_commands(
    *,
    project: str,
    bundle_s3_uri: str,
    bundle_sha256: str,
    data_volume_id: str,
    project_bucket_name: str,
    nvidia_driver_s3_uri: str,
    nvidia_driver_sha256: str,
) -> list[str]:
    group, playbook = _project_group(project)

    if len(bundle_sha256) != 64 or len(nvidia_driver_sha256) != 64:
        raise ValueError("INVALID_SHA256")

    values = {
        "bundle_uri": shlex.quote(bundle_s3_uri),
        "bundle_sha": shlex.quote(bundle_sha256),
        "data_volume_id": shlex.quote(data_volume_id),
        "project_bucket": shlex.quote(project_bucket_name),
        "driver_uri": shlex.quote(nvidia_driver_s3_uri),
        "driver_sha": shlex.quote(nvidia_driver_sha256),
    }

    inventory = (
        "all:\n"
        "  children:\n"
        f"    {group}:\n"
        "      hosts:\n"
        "        localhost:\n"
        "          ansible_connection: local\n"
    )

    return [
        "set -euo pipefail",
        "install -d -m 0700 /var/lib/cloud-media-bootstrap",
        f"aws s3 cp {values['bundle_uri']} /var/lib/cloud-media-bootstrap/config.tar.gz",
        (
            f"echo {values['bundle_sha']}  /var/lib/cloud-media-bootstrap/config.tar.gz "
            "| sha256sum -c -"
        ),
        "rm -rf /var/lib/cloud-media-bootstrap/config",
        "install -d -m 0700 /var/lib/cloud-media-bootstrap/config",
        "tar -xzf /var/lib/cloud-media-bootstrap/config.tar.gz "
        "-C /var/lib/cloud-media-bootstrap/config",
        "python3 -m venv /opt/cloud-media-ansible",
        (
            f"/opt/cloud-media-ansible/bin/pip install --disable-pip-version-check "
            f"ansible-core=={ANSIBLE_CORE_VERSION}"
        ),
        (
            "/opt/cloud-media-ansible/bin/ansible-galaxy collection install "
            "-r /var/lib/cloud-media-bootstrap/config/ansible/requirements.yml"
        ),
        (
            "cat > /var/lib/cloud-media-bootstrap/inventory.yml <<'YAML'\n"
            + inventory
            + "YAML"
        ),
        (
            "/opt/cloud-media-ansible/bin/ansible-playbook "
            "-i /var/lib/cloud-media-bootstrap/inventory.yml "
            f"/var/lib/cloud-media-bootstrap/config/ansible/{playbook} "
            "--extra-vars "
            + shlex.quote(
                " ".join(
                    [
                        f"data_volume_id={data_volume_id}",
                        f"project_bucket_name={project_bucket_name}",
                        f"nvidia_driver_s3_uri={nvidia_driver_s3_uri}",
                        f"nvidia_driver_sha256={nvidia_driver_sha256}",
                    ]
                )
            )
        ),
    ]
