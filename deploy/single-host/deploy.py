#!/usr/bin/env python3
"""Deploy a verified codex-lb image digest to the single-host Compose setup.

The script intentionally uses only the Python standard library.  It is run on
the Docker host, where it serializes service replacement and retains ownership
metadata in a local JSON state file.  It never restores SQLite automatically:
image rollback and database recovery have deliberately separate operators.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parents[1]
STATE_FILE_NAME = "known-good.json"
LOCK_FILE_NAME = "deploy.lock"
BACKUP_PREFIX = "codex-lb-deploy-"
MANAGED_CONTAINER_LABEL = "com.codex-lb.single-host.managed=true"
IMAGE_REFERENCE_PATTERN = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
ENV_KEY_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")
EXPECTED_ENTRYPOINT = ["/app/scripts/docker-entrypoint.sh"]


class DeploymentError(RuntimeError):
    """An actionable deployment failure."""


@dataclass(frozen=True)
class KnownImage:
    image: str
    revision: str

    @classmethod
    def from_mapping(cls, value: object) -> KnownImage | None:
        if not isinstance(value, dict):
            return None
        values = cast(dict[str, object], value)
        image = values.get("image")
        revision = values.get("revision")
        if not isinstance(image, str) or not isinstance(revision, str):
            return None
        if not IMAGE_REFERENCE_PATTERN.fullmatch(image) or not REVISION_PATTERN.fullmatch(revision):
            return None
        return cls(image=image, revision=revision)


@dataclass(frozen=True)
class DeploymentState:
    active: KnownImage | None = None
    previous: KnownImage | None = None
    managed_images: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: Path) -> DeploymentState:
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DeploymentError(f"Cannot read deployment state {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise DeploymentError(f"Deployment state {path} must be a JSON object")

        def read_known_image(name: str) -> KnownImage | None:
            raw_value = raw.get(name)
            if raw_value is None:
                return None
            parsed = KnownImage.from_mapping(raw_value)
            if parsed is None:
                raise DeploymentError(f"Deployment state {path} has invalid {name}")
            return parsed

        active = read_known_image("active")
        previous = read_known_image("previous")
        managed_raw = raw.get("managed_images", [])
        if not isinstance(managed_raw, list) or not all(isinstance(item, str) for item in managed_raw):
            raise DeploymentError(f"Deployment state {path} has invalid managed_images")
        managed_images = tuple(item for item in managed_raw if IMAGE_REFERENCE_PATTERN.fullmatch(item))
        if len(managed_images) != len(set(managed_images)):
            raise DeploymentError(f"Deployment state {path} contains duplicate managed images")
        return cls(active=active, previous=previous, managed_images=managed_images)

    def write(self, path: Path) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = {
            "active": asdict(self.active) if self.active else None,
            "previous": asdict(self.previous) if self.previous else None,
            "managed_images": list(self.managed_images),
        }
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            json.dump(payload, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fchmod(temporary.fileno(), 0o600)
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)


@dataclass(frozen=True)
class DeploymentConfig:
    compose_file: Path
    runtime_env_file: Path
    state_dir: Path
    backup_dir: Path
    project_name: str
    container_name: str
    data_volume: str
    sqlite_database_path: str
    local_ready_url: str
    public_ready_url: str
    min_free_space_mb: int
    health_timeout_seconds: int
    request_timeout_seconds: int
    poll_interval_seconds: float
    backup_retention: int

    @property
    def state_file(self) -> Path:
        return self.state_dir / STATE_FILE_NAME

    @property
    def lock_file(self) -> Path:
        return self.state_dir / LOCK_FILE_NAME

    @classmethod
    def from_file(cls, path: Path) -> DeploymentConfig:
        values = read_environment_file(path)

        def value(name: str, default: str | None = None) -> str:
            selected = os.environ.get(name, values.get(name, default))
            if selected is None or not selected.strip():
                raise DeploymentError(f"Required deployment setting {name} is missing in {path}")
            return selected.strip()

        def integer(name: str, default: str, *, minimum: int = 1) -> int:
            raw = value(name, default)
            try:
                parsed = int(raw)
            except ValueError as exc:
                raise DeploymentError(f"{name} must be an integer, got {raw!r}") from exc
            if parsed < minimum:
                raise DeploymentError(f"{name} must be at least {minimum}, got {parsed}")
            return parsed

        def decimal(name: str, default: str) -> float:
            raw = value(name, default)
            try:
                parsed = float(raw)
            except ValueError as exc:
                raise DeploymentError(f"{name} must be a positive number, got {raw!r}") from exc
            if parsed <= 0:
                raise DeploymentError(f"{name} must be positive, got {parsed}")
            return parsed

        def resolve(raw: str) -> Path:
            candidate = Path(raw).expanduser()
            return candidate if candidate.is_absolute() else (path.parent / candidate).resolve()

        compose_file = resolve(value("DEPLOY_COMPOSE_FILE", str(SCRIPT_DIR / "docker-compose.yml")))
        runtime_env_file = resolve(value("DEPLOY_RUNTIME_ENV_FILE"))
        state_dir = resolve(value("DEPLOY_STATE_DIR", "/var/lib/codex-lb-deploy"))
        backup_dir = resolve(value("DEPLOY_BACKUP_DIR", str(state_dir / "backups")))
        project_name = value("DEPLOY_COMPOSE_PROJECT", "codex-lb")
        container_name = value("DEPLOY_CONTAINER_NAME", "codex-lb-server")
        data_volume = value("DEPLOY_DATA_VOLUME", "codex-lb-data")
        sqlite_database_path = value("DEPLOY_SQLITE_DATABASE_PATH", "/var/lib/codex-lb/store.db")
        local_ready_url = value("DEPLOY_LOCAL_READY_URL", "http://127.0.0.1:2455/health/ready")
        public_ready_url = value("DEPLOY_PUBLIC_READY_URL")

        for name, item in (
            ("DEPLOY_COMPOSE_PROJECT", project_name),
            ("DEPLOY_CONTAINER_NAME", container_name),
            ("DEPLOY_DATA_VOLUME", data_volume),
        ):
            if not NAME_PATTERN.fullmatch(item):
                raise DeploymentError(f"{name} has unsafe Docker name {item!r}")
        if not sqlite_database_path.startswith("/var/lib/codex-lb/"):
            raise DeploymentError("DEPLOY_SQLITE_DATABASE_PATH must stay inside /var/lib/codex-lb/")
        validate_url("DEPLOY_LOCAL_READY_URL", local_ready_url, require_loopback=True)
        validate_url("DEPLOY_PUBLIC_READY_URL", public_ready_url, require_loopback=False)

        if not compose_file.is_file():
            raise DeploymentError(f"Compose file not found: {compose_file}")
        validate_runtime_environment(runtime_env_file)
        return cls(
            compose_file=compose_file,
            runtime_env_file=runtime_env_file,
            state_dir=state_dir,
            backup_dir=backup_dir,
            project_name=project_name,
            container_name=container_name,
            data_volume=data_volume,
            sqlite_database_path=sqlite_database_path,
            local_ready_url=local_ready_url,
            public_ready_url=public_ready_url,
            min_free_space_mb=integer("DEPLOY_MIN_FREE_SPACE_MB", "2048"),
            health_timeout_seconds=integer("DEPLOY_HEALTH_TIMEOUT_SECONDS", "180"),
            request_timeout_seconds=integer("DEPLOY_REQUEST_TIMEOUT_SECONDS", "5"),
            poll_interval_seconds=decimal("DEPLOY_POLL_INTERVAL_SECONDS", "2"),
            backup_retention=integer("DEPLOY_BACKUP_RETENTION", "3"),
        )


def read_environment_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise DeploymentError(f"Deployment configuration file not found: {path}")
    values: dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, raw_value = line.partition("=")
        if not separator or not ENV_KEY_PATTERN.fullmatch(key):
            raise DeploymentError(f"Invalid deployment configuration at {path}:{number}")
        parsed = raw_value.strip()
        if len(parsed) >= 2 and parsed[0] == parsed[-1] and parsed[0] in {"'", '"'}:
            parsed = parsed[1:-1]
        values[key] = parsed
    return values


def validate_url(name: str, value: str, *, require_loopback: bool) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DeploymentError(f"{name} must be a complete http(s) URL")
    if require_loopback and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise DeploymentError(f"{name} must address the local loopback listener")


def validate_runtime_environment(path: Path) -> None:
    if not path.is_file():
        raise DeploymentError(f"Runtime environment file not found: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise DeploymentError(
            f"Runtime environment file {path} must not be accessible to group or others (mode is {mode:03o})"
        )


def parse_candidate(image: str, revision: str) -> KnownImage:
    if not IMAGE_REFERENCE_PATTERN.fullmatch(image):
        raise DeploymentError(
            "--image must be an immutable image reference ending in @sha256:<64 lowercase hex characters>"
        )
    if not REVISION_PATTERN.fullmatch(revision):
        raise DeploymentError("--revision must be a 40- or 64-character lowercase Git revision")
    return KnownImage(image=image, revision=revision)


class SingleHostDeployment:
    def __init__(self, config: DeploymentConfig, candidate: KnownImage) -> None:
        self.config = config
        self.candidate = candidate

    def run(self) -> None:
        self.config.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.config.backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.config.lock_file.open("a+") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DeploymentError(
                    f"Another deployment holds {self.config.lock_file}; refusing concurrent SQLite access"
                ) from exc
            self._run_locked()

    def _run_locked(self) -> None:
        self._compose(self.candidate.image, "config", "-q")
        self._check_free_space()
        self._run_command(["docker", "pull", self.candidate.image])
        self._verify_candidate()

        state = DeploymentState.load(self.config.state_file)
        running = self._running_image()
        if state.active == self.candidate and running == self.candidate:
            self._wait_for_readiness(self.candidate)
            print(f"No-op: {self.candidate.image} is already healthy and active")
            return

        previous = self._select_previous(state, running)
        backup_path = self._backup_sqlite()
        self._prune_backups()

        interrupted = False
        if running is not None:
            self._compose(self.candidate.image, "stop", "server")
            interrupted = True
            if self._container_is_running():
                raise DeploymentError("Compose reported a stop, but the active codex-lb container is still running")

        try:
            self._start(self.candidate)
            self._wait_for_readiness(self.candidate)
        except Exception as original_error:
            if interrupted:
                self._rollback(previous, backup_path, original_error)
            raise

        managed_images = tuple(
            sorted(
                {
                    *state.managed_images,
                    self.candidate.image,
                    *(item.image for item in (previous,) if item is not None),
                }
            )
        )
        next_state = DeploymentState(active=self.candidate, previous=previous, managed_images=managed_images)
        next_state.write(self.config.state_file)
        remaining_images = self._prune_deployment_artifacts(next_state)
        final_state = DeploymentState(active=self.candidate, previous=previous, managed_images=remaining_images)
        final_state.write(self.config.state_file)

        print(f"Deployment succeeded: image={self.candidate.image} revision={self.candidate.revision}")
        if backup_path is not None:
            print(
                f"SQLite backup retained at {backup_path}. It is not restored automatically; "
                "follow deploy/single-host/README.md for an explicit recovery."
            )

    def _compose(self, image: str, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["CODEX_LB_IMAGE"] = image
        environment["CODEX_LB_RUNTIME_ENV_FILE"] = str(self.config.runtime_env_file)
        command = [
            "docker",
            "compose",
            "--project-name",
            self.config.project_name,
            "-f",
            str(self.config.compose_file),
            *arguments,
        ]
        return self._run_command(command, check=check, environment=environment)

    def _run_command(
        self,
        command: list[str],
        *,
        check: bool = True,
        capture_output: bool = False,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            env=environment,
        )
        if check and result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            suffix = f": {details}" if details else ""
            raise DeploymentError(f"Command failed ({shlex.join(command)}){suffix}")
        return result

    def _check_free_space(self) -> None:
        result = self._run_command(["df", "-Pm", str(self.config.state_dir)], capture_output=True)
        lines = result.stdout.splitlines()
        if len(lines) < 2:
            raise DeploymentError(f"Cannot read free space from df output: {result.stdout!r}")
        fields = lines[-1].split()
        if len(fields) < 4:
            raise DeploymentError(f"Cannot parse free space from df output: {lines[-1]!r}")
        try:
            available_mb = int(fields[3])
        except ValueError as exc:
            raise DeploymentError(f"Cannot parse available disk space from df output: {lines[-1]!r}") from exc
        required_mb = self.config.min_free_space_mb
        print(f"Disk preflight: required={required_mb}MiB available={available_mb}MiB path={self.config.state_dir}")
        if available_mb < required_mb:
            raise DeploymentError(
                f"Insufficient free space before image pull: required={required_mb}MiB available={available_mb}MiB "
                f"path={self.config.state_dir}"
            )

    def _inspect_image(self, image: str) -> dict[str, Any]:
        result = self._run_command(["docker", "image", "inspect", image], capture_output=True)
        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise DeploymentError(f"Docker returned invalid image metadata for {image}") from exc
        if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
            raise DeploymentError(f"Docker returned unexpected image metadata for {image}")
        return raw[0]

    def _verify_candidate(self) -> None:
        image = self._inspect_image(self.candidate.image)
        config = image.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        entrypoint = config.get("Entrypoint") if isinstance(config, dict) else None
        if image.get("Os") != "linux" or image.get("Architecture") != "amd64":
            raise DeploymentError(
                "Candidate image must be linux/amd64, got "
                f"{image.get('Os', 'unknown')}/{image.get('Architecture', 'unknown')}"
            )
        if not isinstance(labels, dict) or labels.get("org.opencontainers.image.revision") != self.candidate.revision:
            actual = labels.get("org.opencontainers.image.revision") if isinstance(labels, dict) else None
            raise DeploymentError(
                f"Candidate revision label mismatch: expected={self.candidate.revision} actual={actual or 'missing'}"
            )
        if entrypoint != EXPECTED_ENTRYPOINT:
            raise DeploymentError(
                f"Candidate entrypoint mismatch: expected={EXPECTED_ENTRYPOINT!r} actual={entrypoint!r}"
            )

    def _container_metadata(self) -> dict[str, Any] | None:
        result = self._run_command(
            ["docker", "container", "inspect", self.config.container_name], check=False, capture_output=True
        )
        if result.returncode != 0:
            return None
        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise DeploymentError("Docker returned invalid container metadata") from exc
        if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
            raise DeploymentError("Docker returned unexpected container metadata")
        return raw[0]

    def _running_image(self) -> KnownImage | None:
        container = self._container_metadata()
        if container is None:
            return None
        state = container.get("State")
        if not isinstance(state, dict) or not state.get("Running"):
            return None
        container_config = container.get("Config")
        configured_image = container_config.get("Image") if isinstance(container_config, dict) else None
        image_id = container.get("Image")
        if not isinstance(image_id, str):
            return None
        image = self._inspect_image(image_id)
        image_reference = configured_image if isinstance(configured_image, str) else ""
        if not IMAGE_REFERENCE_PATTERN.fullmatch(image_reference):
            repo_digests = image.get("RepoDigests")
            if isinstance(repo_digests, list):
                image_reference = next(
                    (
                        item
                        for item in repo_digests
                        if isinstance(item, str) and IMAGE_REFERENCE_PATTERN.fullmatch(item)
                    ),
                    "",
                )
        config = image.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        revision = labels.get("org.opencontainers.image.revision") if isinstance(labels, dict) else ""
        return KnownImage.from_mapping({"image": image_reference, "revision": revision})

    def _select_previous(self, state: DeploymentState, running: KnownImage | None) -> KnownImage | None:
        if state.active == self.candidate:
            return state.previous
        if state.active is not None:
            return state.active
        return running

    def _backup_sqlite(self) -> Path | None:
        volume = self._run_command(
            ["docker", "volume", "inspect", self.config.data_volume], check=False, capture_output=True
        )
        if volume.returncode != 0:
            print("No SQLite backup: deployment data volume does not exist yet (first installation)")
            return None

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_path = self.config.backup_dir / f"{BACKUP_PREFIX}{timestamp}.sqlite"
        backup_program = """
import os
import sqlite3
import sys

source_path, destination_path = sys.argv[1:]
if not os.path.isfile(source_path):
    raise SystemExit(20)
source = sqlite3.connect(f\"file:{source_path}?mode=ro\", uri=True)
destination = sqlite3.connect(destination_path)
try:
    source.backup(destination)
    result = destination.execute(\"PRAGMA integrity_check\").fetchone()
    if result != (\"ok\",):
        raise SystemExit(f\"SQLite integrity check failed: {result!r}\")
finally:
    destination.close()
    source.close()
"""
        result = self._run_command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--entrypoint",
                "python",
                "--mount",
                f"type=volume,src={self.config.data_volume},dst=/var/lib/codex-lb",
                "--mount",
                f"type=bind,src={self.config.backup_dir},dst=/backup",
                self.candidate.image,
                "-c",
                backup_program,
                self.config.sqlite_database_path,
                f"/backup/{backup_path.name}",
            ],
            check=False,
            capture_output=True,
        )
        if result.returncode == 20:
            backup_path.unlink(missing_ok=True)
            print("No SQLite backup: database file does not exist yet (first installation)")
            return None
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            raise DeploymentError(f"SQLite backup failed before service replacement: {details}")
        backup_path.chmod(0o600)
        self._verify_backup(backup_path)
        print(f"SQLite backup verified: {backup_path}")
        return backup_path

    @staticmethod
    def _verify_backup(path: Path) -> None:
        if not path.is_file() or path.stat().st_size == 0:
            raise DeploymentError(f"SQLite backup was not created: {path}")
        try:
            with sqlite3.connect(path) as connection:
                result = connection.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.Error as exc:
            raise DeploymentError(f"SQLite backup cannot be opened: {path}: {exc}") from exc
        if result != ("ok",):
            raise DeploymentError(f"SQLite backup integrity check failed: {path}: {result!r}")

    def _prune_backups(self) -> None:
        backups = sorted(
            (
                item
                for item in self.config.backup_dir.iterdir()
                if item.is_file()
                and not item.is_symlink()
                and item.name.startswith(BACKUP_PREFIX)
                and item.suffix == ".sqlite"
            ),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for expired in backups[self.config.backup_retention :]:
            expired.unlink()
            print(f"Removed expired deployment-owned SQLite backup: {expired}")

    def _container_is_running(self) -> bool:
        container = self._container_metadata()
        state = container.get("State") if isinstance(container, dict) else None
        return bool(state.get("Running")) if isinstance(state, dict) else False

    def _start(self, image: KnownImage) -> None:
        self._compose(image.image, "up", "--detach", "--no-build", "--no-deps", "--force-recreate", "server")

    def _wait_for_readiness(self, expected: KnownImage) -> None:
        expected_image = self._inspect_image(expected.image)
        expected_id = expected_image.get("Id")
        deadline = time.monotonic() + self.config.health_timeout_seconds
        last_error = "container did not become ready"
        while time.monotonic() < deadline:
            container = self._container_metadata()
            if container is None:
                last_error = "container does not exist"
            elif container.get("Image") != expected_id:
                last_error = "container does not use the requested image digest"
            else:
                state = container.get("State")
                health = state.get("Health", {}).get("Status") if isinstance(state, dict) else None
                if health == "unhealthy":
                    raise DeploymentError("Container health check reported unhealthy")
                if health != "healthy":
                    last_error = f"Docker health is {health or 'missing'}"
                else:
                    local_error = self._probe(self.config.local_ready_url)
                    public_error = self._probe(self.config.public_ready_url)
                    if local_error is None and public_error is None:
                        return
                    last_error = "; ".join(
                        item
                        for item in (
                            f"local readiness: {local_error}" if local_error else None,
                            f"public readiness: {public_error}" if public_error else None,
                        )
                        if item
                    )
            time.sleep(self.config.poll_interval_seconds)
        raise DeploymentError(
            f"Readiness did not succeed within {self.config.health_timeout_seconds}s for {expected.image}: {last_error}"
        )

    def _probe(self, url: str) -> str | None:
        try:
            with urlopen(url, timeout=self.config.request_timeout_seconds) as response:  # noqa: S310 -- operator config
                if 200 <= response.status < 300:
                    return None
                return f"HTTP {response.status}"
        except (OSError, URLError) as exc:
            return str(exc)

    def _rollback(self, previous: KnownImage | None, backup_path: Path | None, original_error: Exception) -> None:
        if previous is None:
            details = f" Deployment-owned backup: {backup_path}." if backup_path is not None else ""
            raise DeploymentError(
                f"Candidate failed after service interruption ({original_error}); "
                "no prior immutable known-good image is available."
                f"{details} SQLite recovery is a separate explicit operator action."
            ) from original_error
        print(f"Candidate failed; rolling back to image={previous.image} revision={previous.revision}", file=sys.stderr)
        self._compose(self.candidate.image, "stop", "server", check=False)
        self._start(previous)
        self._wait_for_readiness(previous)
        print("Rollback completed and the previous image is healthy", file=sys.stderr)

    def _prune_deployment_artifacts(self, state: DeploymentState) -> tuple[str, ...]:
        if state.active is None:
            raise DeploymentError("Cannot prune deployment artifacts without an active image")
        current_container = self._container_metadata()
        current_id = current_container.get("Id") if isinstance(current_container, dict) else None
        listed = self._run_command(
            ["docker", "ps", "--all", "--quiet", "--filter", f"label={MANAGED_CONTAINER_LABEL}"], capture_output=True
        )
        for container_id in (item for item in listed.stdout.splitlines() if item and item != current_id):
            self._run_command(["docker", "rm", "--force", container_id])
            print(f"Removed deployment-owned stale container: {container_id}")

        keep = {state.active.image}
        if state.previous is not None:
            keep.add(state.previous.image)
        remaining = set(keep)
        for image in state.managed_images:
            if image in keep:
                continue
            result = self._run_command(["docker", "image", "rm", image], check=False, capture_output=True)
            if result.returncode == 0:
                print(f"Removed deployment-owned historical image: {image}")
            else:
                remaining.add(image)
                details = (result.stderr or result.stdout or "").strip()
                print(f"Could not remove deployment-owned image {image}: {details}", file=sys.stderr)
        return tuple(sorted(remaining))


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy one verified codex-lb image digest to the single-host Compose setup."
    )
    parser.add_argument(
        "--config", required=True, type=Path, help="Deployment control file; keep it outside the repository"
    )
    parser.add_argument(
        "--image", required=True, help="Immutable image reference, e.g. ghcr.io/owner/codex-lb@sha256:..."
    )
    parser.add_argument("--revision", required=True, help="Git revision emitted by CI together with the image digest")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(argv if argv is not None else sys.argv[1:])
    try:
        candidate = parse_candidate(arguments.image, arguments.revision)
        config = DeploymentConfig.from_file(arguments.config.expanduser().resolve())
        SingleHostDeployment(config, candidate).run()
    except DeploymentError as exc:
        print(f"Deployment failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
