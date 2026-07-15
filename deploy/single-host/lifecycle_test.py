#!/usr/bin/env python3
"""Run an isolated single-host deploy/update/rollback lifecycle with Docker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parents[1]
FIXTURE_DIR = SCRIPT_DIR / "fixtures" / "lifecycle"
REGISTRY_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    )
)


class LifecycleError(RuntimeError):
    """The isolated Docker lifecycle did not satisfy its contract."""


def _run(
    command: Sequence[str],
    *,
    cwd: Path = REPOSITORY_ROOT,
    environment: dict[str, str] | None = None,
    check: bool = True,
    timeout: int = 600,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        raise LifecycleError(f"command failed ({' '.join(command)}): {details}")
    return result


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_url(url: str, *, timeout_seconds: int = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:  # noqa: S310 -- loopback fixture
                if 200 <= response.status < 300:
                    return
                last_error = f"HTTP {response.status}"
        except (OSError, URLError) as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise LifecycleError(f"fixture URL did not become ready: {url}: {last_error}")


def _registry_digest(registry: str, repository: str, tag: str) -> str:
    request = Request(  # noqa: S310 -- loopback fixture registry
        f"http://{registry}/v2/{repository}/manifests/{tag}",
        method="HEAD",
        headers={"Accept": REGISTRY_ACCEPT},
    )
    with urlopen(request, timeout=5) as response:  # noqa: S310 -- loopback fixture registry
        digest = response.headers.get("Docker-Content-Digest", "")
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise LifecycleError(f"local registry returned invalid digest: {digest!r}")
    return digest


def _build_candidate(registry: str, version: str, revision: str, *, fail_ready: bool) -> tuple[str, str]:
    repository = "codex-lb-lifecycle"
    tag = f"{registry}/{repository}:{version}"
    _run(
        (
            "docker",
            "buildx",
            "build",
            "--load",
            "--platform",
            "linux/amd64",
            "--provenance=false",
            "--build-arg",
            f"VCS_REF={revision}",
            "--build-arg",
            f"FIXTURE_VERSION={version}",
            "--build-arg",
            f"FAIL_READY={int(fail_ready)}",
            "--tag",
            tag,
            ".",
        ),
        cwd=FIXTURE_DIR,
    )
    _run(("docker", "push", tag))
    digest = _registry_digest(registry, repository, version)
    return f"{registry}/{repository}@{digest}", tag


def _write_configuration(
    root: Path,
    *,
    project: str,
    container: str,
    volume: str,
    port: int,
    secret: str,
) -> tuple[Path, Path, Path, Path]:
    runtime = root / "runtime.env"
    runtime.write_text(
        f"CODEX_LB_DATABASE_URL=sqlite+aiosqlite:////var/lib/codex-lb/store.db\nTEST_SECRET={secret}\n",
        encoding="utf-8",
    )
    runtime.chmod(0o600)
    compose = root / "compose.yml"
    compose.write_text(
        f"""services:
  server:
    image: ${{CODEX_LB_IMAGE:?immutable image required}}
    pull_policy: never
    container_name: {container}
    env_file:
      - ${{CODEX_LB_RUNTIME_ENV_FILE:?runtime env required}}
    ports:
      - "127.0.0.1:{port}:2455"
    volumes:
      - data:/var/lib/codex-lb
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - "import urllib.request; urllib.request.urlopen('http://127.0.0.1:2455/health/ready').close()"
      interval: 1s
      timeout: 1s
      retries: 3
      start_period: 1s
    labels:
      com.codex-lb.single-host.managed: "true"
volumes:
  data:
    name: {volume}
    labels:
      com.codex-lb.single-host.managed: "true"
""",
        encoding="utf-8",
    )
    state_dir = root / "state"
    backup_dir = root / "backups"
    control = root / "deployment.env"
    ready_url = f"http://127.0.0.1:{port}/health/ready"
    control.write_text(
        "\n".join(
            (
                f"DEPLOY_RUNTIME_ENV_FILE={runtime}",
                f"DEPLOY_COMPOSE_FILE={compose}",
                f"DEPLOY_STATE_DIR={state_dir}",
                f"DEPLOY_BACKUP_DIR={backup_dir}",
                f"DEPLOY_COMPOSE_PROJECT={project}",
                f"DEPLOY_CONTAINER_NAME={container}",
                f"DEPLOY_DATA_VOLUME={volume}",
                f"DEPLOY_LOCAL_READY_URL={ready_url}",
                f"DEPLOY_PUBLIC_READY_URL={ready_url}",
                "DEPLOY_MIN_FREE_SPACE_MB=64",
                "DEPLOY_HEALTH_TIMEOUT_SECONDS=15",
                "DEPLOY_REQUEST_TIMEOUT_SECONDS=1",
                "DEPLOY_POLL_INTERVAL_SECONDS=0.25",
                "DEPLOY_BACKUP_RETENTION=3",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return runtime, compose, control, state_dir


def _write_release_manifest(path: Path, image: str, revision: str) -> None:
    repository, digest = image.rsplit("@", 1)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repository": repository,
                "revision": revision,
                "digest": digest,
                "image": image,
                "platform": "linux/amd64",
                "ready": True,
                "gates": {
                    "validation": {"status": "passed", "detail": "isolated lifecycle fixture"},
                    "revision": {"status": "passed", "detail": "fixture OCI revision"},
                    "security": {"status": "passed", "detail": "minimal isolated fixture"},
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _deploy(command: str, config: Path, manifest: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        (
            sys.executable,
            str(SCRIPT_DIR / "deploy.py"),
            command,
            "--config",
            str(config),
            "--manifest",
            str(manifest),
            *(("--json",) if command == "doctor" else ()),
        ),
        environment={**os.environ, "CODEX_LB_TEST_ALLOW_LOOPBACK_MANIFEST": "1"},
        timeout=120,
    )


def _service_state(port: int) -> dict[str, object]:
    with urlopen(f"http://127.0.0.1:{port}/state", timeout=2) as response:  # noqa: S310 -- fixture
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise LifecycleError("fixture returned a non-object state payload")
    return payload


def run_lifecycle() -> dict[str, object]:
    suffix = uuid.uuid4().hex[:12]
    registry_name = f"codex-lb-registry-{suffix}"
    project = f"codex-lb-life-{suffix}"
    container = f"codex-lb-life-server-{suffix}"
    volume = f"codex-lb-life-data-{suffix}"
    network = f"{project}_default"
    registry_port = _free_port()
    service_port = _free_port()
    registry = f"127.0.0.1:{registry_port}"
    secret = f"lifecycle-secret-{suffix}"
    secret_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    image_references: list[str] = []
    image_tags: list[str] = []
    transcript: list[str] = []
    cleanup_passed = False
    result: dict[str, object] | None = None

    with tempfile.TemporaryDirectory(prefix="codex-lb-lifecycle-") as directory:
        root = Path(directory)
        runtime, compose, control, state_dir = _write_configuration(
            root,
            project=project,
            container=container,
            volume=volume,
            port=service_port,
            secret=secret,
        )
        compose_environment = {
            **os.environ,
            "CODEX_LB_IMAGE": "busybox@sha256:" + "0" * 64,
            "CODEX_LB_RUNTIME_ENV_FILE": str(runtime),
        }
        try:
            registry_run = _run(
                (
                    "docker",
                    "run",
                    "--detach",
                    "--name",
                    registry_name,
                    "--publish",
                    f"127.0.0.1:{registry_port}:5000",
                    "registry:2",
                ),
                timeout=180,
            )
            transcript.extend((registry_run.stdout, registry_run.stderr))
            _wait_for_url(f"http://{registry}/v2/")

            first_revision, second_revision, bad_revision = "a" * 40, "b" * 40, "c" * 40
            first_image, first_tag = _build_candidate(registry, "initial", first_revision, fail_ready=False)
            second_image, second_tag = _build_candidate(registry, "next", second_revision, fail_ready=False)
            bad_image, bad_tag = _build_candidate(registry, "unready", bad_revision, fail_ready=True)
            image_references.extend((first_image, second_image, bad_image))
            image_tags.extend((first_tag, second_tag, bad_tag))
            first_manifest = root / "initial-release.json"
            second_manifest = root / "next-release.json"
            bad_manifest = root / "unready-release.json"
            _write_release_manifest(first_manifest, first_image, first_revision)
            _write_release_manifest(second_manifest, second_image, second_revision)
            _write_release_manifest(bad_manifest, bad_image, bad_revision)

            doctor = _deploy("doctor", control, first_manifest)
            transcript.extend((doctor.stdout, doctor.stderr))
            doctor_payload = json.loads(doctor.stdout)
            if doctor_payload.get("ok") is not True:
                raise LifecycleError(f"doctor rejected isolated fixture: {doctor.stdout}")

            initial = _deploy("deploy", control, first_manifest)
            transcript.extend((initial.stdout, initial.stderr))
            initial_state = _service_state(service_port)
            if initial_state != {"accounts": 1, "api_keys": 1, "secret_hash": secret_hash, "version": "initial"}:
                raise LifecycleError(f"unexpected initial state: {initial_state}")

            update = _deploy("deploy", control, second_manifest)
            transcript.extend((update.stdout, update.stderr))
            updated_state = _service_state(service_port)
            running_after_update = _run(
                ("docker", "container", "inspect", "--format", "{{.Config.Image}}", container)
            ).stdout.strip()
            if updated_state != {"accounts": 1, "api_keys": 1, "secret_hash": secret_hash, "version": "next"}:
                raise LifecycleError(f"state changed during successful update: {updated_state}")
            if running_after_update != second_image:
                raise LifecycleError(f"successful update runs {running_after_update}, expected {second_image}")

            failed = _run(
                (
                    sys.executable,
                    str(SCRIPT_DIR / "deploy.py"),
                    "--config",
                    str(control),
                    "--manifest",
                    str(bad_manifest),
                ),
                environment={**os.environ, "CODEX_LB_TEST_ALLOW_LOOPBACK_MANIFEST": "1"},
                check=False,
                timeout=120,
            )
            transcript.extend((failed.stdout, failed.stderr))
            if failed.returncode == 0:
                raise LifecycleError("unready candidate unexpectedly succeeded")
            _wait_for_url(f"http://127.0.0.1:{service_port}/health/ready")
            rolled_back_state = _service_state(service_port)
            running_after_rollback = _run(
                ("docker", "container", "inspect", "--format", "{{.Config.Image}}", container)
            ).stdout.strip()
            deploy_state = json.loads((state_dir / "known-good.json").read_text(encoding="utf-8"))
            last_event = json.loads((state_dir / "deploy-events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            if rolled_back_state != updated_state:
                raise LifecycleError(f"rollback changed persistent state: {rolled_back_state}")
            if running_after_rollback != second_image or deploy_state["active"]["image"] != second_image:
                raise LifecycleError("rollback did not restore the actual previous digest")
            if last_event["outcome"] != "rollback_succeeded" or last_event["running"]["image"] != second_image:
                raise LifecycleError(f"rollback event is incorrect: {last_event}")
            if any(secret in output for output in transcript):
                raise LifecycleError("test secret leaked into command output")

            result = {
                "schema_version": 1,
                "initial_deploy": "passed",
                "successful_update": "passed",
                "state_preserved": "passed",
                "rollback": "passed",
                "cleanup": "pending",
            }
        finally:
            _run(
                (
                    "docker",
                    "compose",
                    "--project-name",
                    project,
                    "-f",
                    str(compose),
                    "down",
                    "--volumes",
                    "--remove-orphans",
                ),
                environment=compose_environment,
                check=False,
            )
            _run(("docker", "rm", "--force", registry_name), check=False)
            if image_references or image_tags:
                _run(("docker", "image", "rm", "--force", *image_references, *image_tags), check=False)
            container_exists = _run(("docker", "container", "inspect", container), check=False).returncode == 0
            volume_exists = _run(("docker", "volume", "inspect", volume), check=False).returncode == 0
            network_exists = _run(("docker", "network", "inspect", network), check=False).returncode == 0
            registry_exists = _run(("docker", "container", "inspect", registry_name), check=False).returncode == 0
            cleanup_passed = not any((container_exists, volume_exists, network_exists, registry_exists))

    if not cleanup_passed:
        raise LifecycleError("temporary Docker resources remain after lifecycle cleanup")
    if result is None:
        raise LifecycleError("lifecycle ended before producing a result")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit a machine-readable result")
    args = parser.parse_args(argv)
    try:
        result = run_lifecycle()
    except (LifecycleError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        parser.exit(1, f"single-host lifecycle failed: {exc}\n")
    result["cleanup"] = "passed"
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print("Single-host Docker lifecycle passed: initial -> update -> rollback; resources cleaned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
