#!/usr/bin/env python3
"""Build and publish a verified single-host release candidate to GHCR."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, Sequence

from scripts.ci_scope import classify_paths

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
REPOSITORY_PATTERN = re.compile(r"^ghcr\.io/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._/-]*$")
PLATFORM = "linux/amd64"
SCHEMA_VERSION = 1


class LocalReleaseError(RuntimeError):
    """A release invariant failed with an actionable explanation."""


@dataclass(frozen=True, slots=True)
class GateResult:
    status: str
    detail: str

    @classmethod
    def passed(cls, detail: str) -> GateResult:
        return cls(status="passed", detail=detail)

    @classmethod
    def failed(cls, detail: str) -> GateResult:
        return cls(status="failed", detail=detail)


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    schema_version: int
    repository: str
    revision: str
    digest: str
    image: str
    platform: str
    ready: bool
    generated_at: str
    gates: dict[str, GateResult]

    @classmethod
    def ready_candidate(
        cls,
        *,
        repository: str,
        revision: str,
        digest: str,
        validation: GateResult,
        revision_gate: GateResult,
        security_gate: GateResult,
    ) -> ReleaseManifest:
        validate_repository(repository)
        validate_revision(revision)
        validate_digest(digest)
        gates = {
            "validation": validation,
            "revision": revision_gate,
            "security": security_gate,
        }
        return cls(
            schema_version=SCHEMA_VERSION,
            repository=repository,
            revision=revision,
            digest=digest,
            image=f"{repository}@{digest}",
            platform=PLATFORM,
            ready=all(gate.status == "passed" for gate in gates.values()),
            generated_at=datetime.now(UTC).isoformat(),
            gates=gates,
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(self.to_json(), encoding="utf-8")
        temporary.replace(path)


def validate_repository(repository: str) -> None:
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise LocalReleaseError("repository must be an untagged lowercase GHCR path such as ghcr.io/owner/codex-lb")


def validate_revision(revision: str) -> None:
    if not SHA_PATTERN.fullmatch(revision):
        raise LocalReleaseError("revision must be a full 40-character lowercase Git SHA")


def validate_digest(digest: str) -> None:
    if not DIGEST_PATTERN.fullmatch(digest):
        raise LocalReleaseError("published image digest must be sha256 followed by 64 lowercase hex characters")


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        check=True,
        capture_output=capture_output,
    )


def validate_published_sha(repository_root: Path, revision: str, remote: str) -> None:
    """Require an exact commit contained by a fetched branch of *remote*."""

    validate_revision(revision)
    try:
        _run(("git", "cat-file", "-e", f"{revision}^{{commit}}"), cwd=repository_root)
        _run(("git", "fetch", "--prune", remote), cwd=repository_root)
        refs = _run(
            (
                "git",
                "for-each-ref",
                "--format=%(refname)",
                "--contains",
                revision,
                f"refs/remotes/{remote}/",
            ),
            cwd=repository_root,
            capture_output=True,
        ).stdout.splitlines()
    except subprocess.CalledProcessError as exc:
        raise LocalReleaseError(f"cannot verify Git revision {revision} against remote {remote}") from exc
    if not refs:
        raise LocalReleaseError(f"revision {revision} is not published on any fetched {remote} branch")


@contextmanager
def detached_worktree(repository_root: Path, revision: str) -> Iterator[Path]:
    """Yield a clean detached worktree and remove it after every outcome."""

    with tempfile.TemporaryDirectory(prefix="codex-lb-release-worktree-") as directory:
        worktree = Path(directory) / "source"
        try:
            _run(("git", "worktree", "add", "--detach", str(worktree), revision), cwd=repository_root)
            yield worktree
        finally:
            subprocess.run(
                ("git", "worktree", "remove", "--force", str(worktree)),
                cwd=repository_root,
                check=False,
                capture_output=True,
                text=True,
            )


def buildx_command(
    *,
    repository: str,
    revision: str,
    metadata_file: Path,
    cache_source: Path | None,
    cache_destination: Path,
) -> tuple[str, ...]:
    validate_repository(repository)
    validate_revision(revision)
    command = [
        "docker",
        "buildx",
        "build",
        "--platform",
        PLATFORM,
        "--push",
        "--tag",
        f"{repository}:sha-{revision}",
        "--build-arg",
        f"VCS_REF={revision}",
        "--provenance=false",
        "--sbom=false",
        "--metadata-file",
        str(metadata_file),
    ]
    if cache_source is not None:
        command.extend(("--cache-from", f"type=local,src={cache_source}"))
    command.extend(("--cache-to", f"type=local,dest={cache_destination},mode=max", "."))
    return tuple(command)


def select_validation_target(repository_root: Path, revision: str, *, force_full: bool) -> str:
    if force_full:
        return "ci"
    parents = _run(
        ("git", "rev-list", "--parents", "--max-count=1", revision),
        cwd=repository_root,
        capture_output=True,
    ).stdout.split()
    if len(parents) > 2:
        return "ci"
    changed = _run(
        ("git", "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", revision),
        cwd=repository_root,
        capture_output=True,
    ).stdout.splitlines()
    return "ci" if classify_paths(changed).level == "full" else "fork-contract"


def _diagnose_release_environment(repository_root: Path, username: str, token: str) -> None:
    with tempfile.TemporaryDirectory(prefix="codex-lb-dry-run-docker-config-") as docker_config:
        docker_config_path = Path(docker_config)
        docker_config_path.chmod(0o700)
        environment = {**os.environ, "DOCKER_CONFIG": str(docker_config_path)}
        _run(("docker", "info"), cwd=repository_root, env=environment, capture_output=True)
        _run(("docker", "buildx", "version"), cwd=repository_root, env=environment, capture_output=True)
        _run(("trivy", "--version"), cwd=repository_root, env=environment, capture_output=True)
        _run(
            ("docker", "login", "ghcr.io", "--username", username, "--password-stdin"),
            cwd=repository_root,
            env=environment,
            input_text=token,
            capture_output=True,
        )


def _require_programs(programs: Sequence[str]) -> None:
    missing = [program for program in programs if shutil.which(program) is None]
    if missing:
        raise LocalReleaseError(f"required programs are unavailable: {', '.join(missing)}")


def _read_digest(metadata_file: Path) -> str:
    try:
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        digest = metadata["containerimage.digest"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise LocalReleaseError("buildx metadata does not contain containerimage.digest") from exc
    if not isinstance(digest, str):
        raise LocalReleaseError("buildx returned a non-string image digest")
    validate_digest(digest)
    return digest


def _inspect_revision(image: str, *, worktree: Path, env: dict[str, str]) -> str:
    result = _run(
        (
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            image,
            "--format",
            "{{json .Image.Config.Labels}}",
        ),
        cwd=worktree,
        env=env,
        capture_output=True,
    )
    try:
        labels = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise LocalReleaseError("cannot parse OCI labels from the published image") from exc
    revision = labels.get("org.opencontainers.image.revision") if isinstance(labels, dict) else None
    if not isinstance(revision, str):
        raise LocalReleaseError("published image has no org.opencontainers.image.revision label")
    return revision


def _rotate_cache(cache: Path, candidate: Path) -> None:
    if not candidate.exists():
        raise LocalReleaseError("buildx did not create the requested local cache")
    shutil.rmtree(cache, ignore_errors=True)
    candidate.replace(cache)


def release_candidate(
    *,
    repository_root: Path,
    revision: str,
    remote: str,
    image_repository: str,
    manifest_path: Path,
    cache_path: Path,
    force_full: bool,
    dry_run: bool,
) -> ReleaseManifest | dict[str, object]:
    validate_repository(image_repository)
    validate_published_sha(repository_root, revision, remote)
    _require_programs(("docker", "trivy", "make"))
    username = os.environ.get("GITHUB_USER", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "")
    if not username or not token:
        raise LocalReleaseError("GITHUB_USER and GITHUB_TOKEN are required for GHCR publication")
    validation_target = select_validation_target(repository_root, revision, force_full=force_full)
    if dry_run:
        _diagnose_release_environment(repository_root, username, token)
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": "dry-run",
            "repository": image_repository,
            "revision": revision,
            "platform": PLATFORM,
            "validation_target": validation_target,
            "diagnostics": ["docker", "buildx", "trivy", "ghcr_auth"],
            "ready": False,
        }

    cache_path = cache_path.expanduser().resolve()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_candidate = cache_path.with_name(f"{cache_path.name}.next")
    shutil.rmtree(cache_candidate, ignore_errors=True)
    try:
        with (
            detached_worktree(repository_root, revision) as worktree,
            tempfile.TemporaryDirectory(prefix="codex-lb-docker-config-") as docker_config,
            tempfile.TemporaryDirectory(prefix="codex-lb-release-metadata-") as metadata_directory,
        ):
            docker_config_path = Path(docker_config)
            docker_config_path.chmod(0o700)
            environment = {**os.environ, "DOCKER_CONFIG": str(docker_config_path)}
            _run(("make", validation_target), cwd=worktree)
            _run(
                ("docker", "login", "ghcr.io", "--username", username, "--password-stdin"),
                cwd=worktree,
                env=environment,
                input_text=token,
            )
            metadata_file = Path(metadata_directory) / "buildx-metadata.json"
            source_cache = cache_path if (cache_path / "index.json").is_file() else None
            _run(
                buildx_command(
                    repository=image_repository,
                    revision=revision,
                    metadata_file=metadata_file,
                    cache_source=source_cache,
                    cache_destination=cache_candidate,
                ),
                cwd=worktree,
                env=environment,
            )
            digest = _read_digest(metadata_file)
            image = f"{image_repository}@{digest}"
            actual_revision = _inspect_revision(image, worktree=worktree, env=environment)
            if actual_revision != revision:
                failed = ReleaseManifest.ready_candidate(
                    repository=image_repository,
                    revision=revision,
                    digest=digest,
                    validation=GateResult.passed(validation_target),
                    revision_gate=GateResult.failed(f"published revision is {actual_revision}"),
                    security_gate=GateResult.failed("not run because revision verification failed"),
                )
                failed.write(manifest_path)
                raise LocalReleaseError(
                    f"published OCI revision {actual_revision!r} does not match selected SHA {revision}"
                )
            try:
                _run(
                    (
                        "trivy",
                        "image",
                        "--format",
                        "table",
                        "--exit-code",
                        "1",
                        "--severity",
                        "CRITICAL,HIGH",
                        "--ignore-unfixed",
                        image,
                    ),
                    cwd=worktree,
                    env=environment,
                )
            except subprocess.CalledProcessError as exc:
                failed = ReleaseManifest.ready_candidate(
                    repository=image_repository,
                    revision=revision,
                    digest=digest,
                    validation=GateResult.passed(validation_target),
                    revision_gate=GateResult.passed("OCI revision matches"),
                    security_gate=GateResult.failed("Trivy found a blocking vulnerability"),
                )
                failed.write(manifest_path)
                raise LocalReleaseError("published digest failed the Trivy security gate") from exc
            manifest = ReleaseManifest.ready_candidate(
                repository=image_repository,
                revision=revision,
                digest=digest,
                validation=GateResult.passed(validation_target),
                revision_gate=GateResult.passed("OCI revision matches"),
                security_gate=GateResult.passed("Trivy CRITICAL,HIGH --ignore-unfixed"),
            )
            manifest.write(manifest_path)
        _rotate_cache(cache_path, cache_candidate)
        return manifest
    finally:
        shutil.rmtree(cache_candidate, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True, help="full published Git commit SHA")
    parser.add_argument("--repository", required=True, help="untagged lowercase GHCR repository")
    parser.add_argument("--remote", default="origin", help="fork Git remote (default: origin)")
    parser.add_argument("--manifest", type=Path, help="candidate manifest output path")
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("~/.cache/codex-lb/buildx"),
        help="reusable local buildx cache",
    )
    parser.add_argument("--full", action="store_true", help="force the full validation target")
    parser.add_argument("--dry-run", action="store_true", help="check prerequisites without publishing")
    args = parser.parse_args(argv)
    manifest_path = args.manifest or Path(f"release-manifest-{args.sha[:12]}.json")
    try:
        result = release_candidate(
            repository_root=REPOSITORY_ROOT,
            revision=args.sha,
            remote=args.remote,
            image_repository=args.repository,
            manifest_path=manifest_path,
            cache_path=args.cache,
            force_full=args.full,
            dry_run=args.dry_run,
        )
    except (LocalReleaseError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"local release failed: {exc}\n")
    print(result.to_json() if isinstance(result, ReleaseManifest) else json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
