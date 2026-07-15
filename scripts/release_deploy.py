#!/usr/bin/env python3
"""Publish a candidate locally, then diagnose and deploy it over SSH."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from scripts.local_release import DIGEST_PATTERN, REPOSITORY_PATTERN, SHA_PATTERN

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SSH_TARGET_PATTERN = re.compile(r"^(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9._-]+$")
REMOTE_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9._/-]+$")


class ReleaseDeployError(RuntimeError):
    """The operator release/deploy flow failed."""


@dataclass(frozen=True, slots=True)
class OperatorResult:
    schema_version: int
    revision: str
    image: str
    host: str
    doctor: str
    deploy: str
    final_verification: str


def _run(command: Sequence[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=capture_output,
        text=True,
    )


def _validate_remote(target: str, repository: str, config: str) -> None:
    if not SSH_TARGET_PATTERN.fullmatch(target):
        raise ReleaseDeployError("SSH target must be [user@]host without shell metacharacters")
    for label, path in (("remote repository", repository), ("remote config", config)):
        if not REMOTE_PATH_PATTERN.fullmatch(path) or ".." in Path(path).parts:
            raise ReleaseDeployError(f"{label} must be a simple absolute POSIX path")


def _ssh_command(target: str, arguments: Sequence[str]) -> tuple[str, ...]:
    return ("ssh", "--", target, shlex.join(arguments))


def _doctor_payload(output: str, expected_image: str, *, final: bool) -> None:
    try:
        payload = json.loads(output)
        checks = payload["checks"]
        deployment_state = payload["deployment_state"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ReleaseDeployError("remote doctor returned invalid JSON") from exc
    if payload.get("schema_version") != 1 or payload.get("ok") is not True or not isinstance(checks, list):
        raise ReleaseDeployError("remote doctor reported a failed prerequisite")
    if final:
        if (
            not isinstance(deployment_state, dict)
            or deployment_state.get("active_image") != expected_image
            or deployment_state.get("running_image") != expected_image
        ):
            raise ReleaseDeployError("final doctor did not confirm the deployed digest")


def release_and_deploy(
    *,
    revision: str,
    image_repository: str,
    target: str,
    remote_repository: str,
    remote_config: str,
    manifest_path: Path,
    force_full: bool,
    use_sudo: bool,
) -> OperatorResult:
    if not SHA_PATTERN.fullmatch(revision):
        raise ReleaseDeployError("revision must be a full lowercase Git SHA")
    if not REPOSITORY_PATTERN.fullmatch(image_repository):
        raise ReleaseDeployError("repository must be an untagged lowercase GHCR path")
    _validate_remote(target, remote_repository, remote_config)
    manifest_path = manifest_path.expanduser().resolve()
    release_command = [
        sys.executable,
        "-m",
        "scripts.local_release",
        "--sha",
        revision,
        "--repository",
        image_repository,
        "--manifest",
        str(manifest_path),
    ]
    if force_full:
        release_command.append("--full")
    _run(release_command)

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        image = manifest["image"]
        digest = manifest["digest"]
        gates = manifest["gates"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ReleaseDeployError("local release did not create a valid manifest") from exc
    if (
        manifest.get("ready") is not True
        or manifest.get("schema_version") != 1
        or manifest.get("repository") != image_repository
        or manifest.get("revision") != revision
        or manifest.get("platform") != "linux/amd64"
        or not isinstance(image, str)
        or not isinstance(digest, str)
        or not isinstance(gates, dict)
        or any(
            not isinstance(gates.get(name), dict) or gates[name].get("status") != "passed"
            for name in ("validation", "revision", "security")
        )
        or not DIGEST_PATTERN.fullmatch(digest)
        or image != f"{image_repository}@{digest}"
    ):
        raise ReleaseDeployError("local release manifest is not a ready candidate for the requested SHA")

    remote_manifest = f"/tmp/codex-lb-release-{revision[:12]}.json"
    deploy_script = f"{remote_repository}/deploy/single-host/deploy.py"
    privilege = ["sudo"] if use_sudo else []
    base = [*privilege, "python3", deploy_script]
    doctor = [*base, "doctor", "--config", remote_config, "--manifest", remote_manifest, "--json"]
    deploy = [*base, "deploy", "--config", remote_config, "--manifest", remote_manifest]
    cleanup = _ssh_command(target, [*privilege, "rm", "-f", remote_manifest])

    try:
        _run(("scp", "--", str(manifest_path), f"{target}:{remote_manifest}"))
        before = _run(_ssh_command(target, doctor), capture_output=True)
        _doctor_payload(before.stdout, image, final=False)
        _run(_ssh_command(target, deploy))
        after = _run(_ssh_command(target, doctor), capture_output=True)
        _doctor_payload(after.stdout, image, final=True)
    finally:
        _run(cleanup, capture_output=True)

    return OperatorResult(
        schema_version=1,
        revision=revision,
        image=image,
        host=target,
        doctor="passed",
        deploy="passed",
        final_verification="passed",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--host", required=True, help="SSH target in [user@]host form")
    parser.add_argument("--remote-repository", required=True, help="absolute path to the repository checkout on host")
    parser.add_argument("--remote-config", default="/etc/codex-lb/deployment.env")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--sudo", action="store_true", help="run remote deploy and cleanup through sudo")
    args = parser.parse_args(argv)
    manifest = args.manifest or Path(f"release-manifest-{args.sha[:12]}.json")
    try:
        result = release_and_deploy(
            revision=args.sha,
            image_repository=args.repository,
            target=args.host,
            remote_repository=args.remote_repository,
            remote_config=args.remote_config,
            manifest_path=manifest,
            force_full=args.full,
            use_sudo=args.sudo,
        )
    except (ReleaseDeployError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"release and deploy failed: {exc}\n")
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
