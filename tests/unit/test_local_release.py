import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.local_release import (
    GateResult,
    LocalReleaseError,
    ReleaseManifest,
    buildx_command,
    detached_worktree,
    release_candidate,
    select_validation_target,
    validate_published_sha,
)


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repository, check=True, capture_output=True, text=True).stdout.strip()


def _repository_with_remote(tmp_path: Path) -> tuple[Path, Path, str]:
    remote = tmp_path / "remote.git"
    repository = tmp_path / "source"
    subprocess.run(["git", "init", "--bare", "-q", remote], check=True)
    subprocess.run(["git", "init", "-q", repository], check=True)
    _git(repository, "config", "user.email", "release@example.invalid")
    _git(repository, "config", "user.name", "Release Test")
    (repository / "tracked.txt").write_text("published\n", encoding="utf-8")
    (repository / "Makefile").write_text("fork-contract:\n\t@true\n\nci:\n\t@true\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "published")
    _git(repository, "remote", "add", "origin", str(remote))
    _git(repository, "push", "-q", "-u", "origin", "HEAD:main")
    return repository, remote, _git(repository, "rev-parse", "HEAD")


def _install_fake_release_tools(tmp_path: Path, monkeypatch) -> Path:
    binary_dir = tmp_path / "bin"
    state_dir = tmp_path / "fake-release-state"
    binary_dir.mkdir()
    state_dir.mkdir()
    docker = binary_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state = Path(os.environ["FAKE_RELEASE_STATE"])
args = sys.argv[1:]
if args[0] == "login":
    sys.stdin.read()
    (state / "docker-config.txt").write_text(os.environ["DOCKER_CONFIG"])
elif args == ["info"] or args[:2] == ["buildx", "version"]:
    pass
elif args[:2] == ["buildx", "build"]:
    if os.environ.get("FAKE_DOCKER_FAIL_BUILD") == "1":
        raise SystemExit(42)
    revision = args[args.index("--build-arg") + 1].split("=", 1)[1]
    (state / "revision.txt").write_text(revision)
    metadata = Path(args[args.index("--metadata-file") + 1])
    metadata.write_text(json.dumps({"containerimage.digest": "sha256:" + "a" * 64}))
    cache_to = args[args.index("--cache-to") + 1]
    cache = Path(cache_to.split("dest=", 1)[1].split(",", 1)[0])
    cache.mkdir(parents=True)
    (cache / "index.json").write_text("{}")
elif args[:3] == ["buildx", "imagetools", "inspect"]:
    revision = (state / "revision.txt").read_text()
    print(json.dumps({"org.opencontainers.image.revision": revision}))
else:
    raise SystemExit(f"unexpected fake docker command: {args}")
""",
        encoding="utf-8",
    )
    trivy = binary_dir / "trivy"
    trivy.write_text(
        """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

state = Path(os.environ["FAKE_RELEASE_STATE"])
with (state / "trivy-calls.txt").open("a") as output:
    output.write(" ".join(sys.argv[1:]) + "\\n")
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    trivy.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binary_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_RELEASE_STATE", str(state_dir))
    monkeypatch.setenv("GITHUB_USER", "release-test")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-survive")
    return state_dir


def test_release_manifest_is_versioned_immutable_and_contains_no_credentials() -> None:
    digest = "sha256:" + "a" * 64
    manifest = ReleaseManifest.ready_candidate(
        repository="ghcr.io/example/codex-lb",
        revision="b" * 40,
        digest=digest,
        validation=GateResult.passed("fork-contract"),
        revision_gate=GateResult.passed("OCI revision matches"),
        security_gate=GateResult.passed("CRITICAL,HIGH"),
    )

    payload = json.loads(manifest.to_json())

    assert payload["schema_version"] == 1
    assert payload["image"] == f"ghcr.io/example/codex-lb@{digest}"
    assert payload["platform"] == "linux/amd64"
    assert payload["ready"] is True
    assert "token" not in manifest.to_json().lower()
    assert "password" not in manifest.to_json().lower()


def test_unpublished_sha_is_rejected_before_release(tmp_path: Path) -> None:
    repository, _remote, _published_sha = _repository_with_remote(tmp_path)
    (repository / "tracked.txt").write_text("local only\n", encoding="utf-8")
    _git(repository, "commit", "-qam", "local only")
    local_sha = _git(repository, "rev-parse", "HEAD")

    with pytest.raises(LocalReleaseError, match="not published"):
        validate_published_sha(repository, local_sha, "origin")


def test_detached_worktree_excludes_dirty_source_and_is_removed(tmp_path: Path) -> None:
    repository, _remote, published_sha = _repository_with_remote(tmp_path)
    dirty_file = repository / "uncommitted.txt"
    dirty_file.write_text("must not be released\n", encoding="utf-8")
    worktree_path: Path | None = None

    with detached_worktree(repository, published_sha) as worktree:
        worktree_path = worktree
        assert _git(worktree, "rev-parse", "HEAD") == published_sha
        assert not (worktree / dirty_file.name).exists()

    assert worktree_path is not None
    assert not worktree_path.exists()


def test_buildx_command_publishes_one_amd64_candidate_with_reusable_cache(tmp_path: Path) -> None:
    command = buildx_command(
        repository="ghcr.io/example/codex-lb",
        revision="c" * 40,
        metadata_file=tmp_path / "metadata.json",
        cache_source=tmp_path / "cache",
        cache_destination=tmp_path / "cache-next",
    )

    assert command[:3] == ("docker", "buildx", "build")
    assert ("--platform", "linux/amd64") == command[3:5]
    assert "--push" in command
    assert "ghcr.io/example/codex-lb:sha-" + "c" * 40 in command
    assert "type=local,src=" + str(tmp_path / "cache") in command
    assert "type=local,dest=" + str(tmp_path / "cache-next") + ",mode=max" in command


def test_merge_commit_always_selects_full_validation(tmp_path: Path) -> None:
    repository, _remote, _revision = _repository_with_remote(tmp_path)
    _git(repository, "checkout", "-qb", "topic")
    (repository / "topic.txt").write_text("topic\n", encoding="utf-8")
    _git(repository, "add", "topic.txt")
    _git(repository, "commit", "-qm", "topic")
    _git(repository, "checkout", "-q", "main")
    (repository / "main.txt").write_text("main\n", encoding="utf-8")
    _git(repository, "add", "main.txt")
    _git(repository, "commit", "-qm", "main")
    _git(repository, "merge", "--no-ff", "-qm", "merge topic", "topic")
    revision = _git(repository, "rev-parse", "HEAD")

    assert select_validation_target(repository, revision, force_full=False) == "ci"


def test_release_candidate_scans_published_digest_once_and_cleans_credentials(tmp_path: Path, monkeypatch) -> None:
    repository, _remote, revision = _repository_with_remote(tmp_path)
    state_dir = _install_fake_release_tools(tmp_path, monkeypatch)
    manifest_path = tmp_path / "candidate.json"
    cache_path = tmp_path / "cache"

    manifest = release_candidate(
        repository_root=repository,
        revision=revision,
        remote="origin",
        image_repository="ghcr.io/example/codex-lb",
        manifest_path=manifest_path,
        cache_path=cache_path,
        force_full=False,
        dry_run=False,
    )

    assert isinstance(manifest, ReleaseManifest)
    assert manifest.ready is True
    assert manifest_path.is_file()
    assert len((state_dir / "trivy-calls.txt").read_text().splitlines()) == 1
    docker_config = Path((state_dir / "docker-config.txt").read_text())
    assert not docker_config.exists()
    assert (cache_path / "index.json").is_file()
    assert "must-not-survive" not in manifest_path.read_text(encoding="utf-8")


def test_dry_run_checks_release_plan_without_registry_mutation(tmp_path: Path, monkeypatch) -> None:
    repository, _remote, revision = _repository_with_remote(tmp_path)
    state_dir = _install_fake_release_tools(tmp_path, monkeypatch)

    result = release_candidate(
        repository_root=repository,
        revision=revision,
        remote="origin",
        image_repository="ghcr.io/example/codex-lb",
        manifest_path=tmp_path / "candidate.json",
        cache_path=tmp_path / "cache",
        force_full=False,
        dry_run=True,
    )

    assert isinstance(result, dict)
    assert result["mode"] == "dry-run"
    assert result["validation_target"] == "ci"
    assert result["diagnostics"] == ["docker", "buildx", "trivy", "ghcr_auth"]
    docker_config = Path((state_dir / "docker-config.txt").read_text())
    assert not docker_config.exists()
    assert (state_dir / "trivy-calls.txt").read_text().splitlines() == ["--version"]
    assert not (tmp_path / "candidate.json").exists()


def test_failed_build_cleans_worktree_and_temporary_docker_config(tmp_path: Path, monkeypatch) -> None:
    repository, _remote, revision = _repository_with_remote(tmp_path)
    state_dir = _install_fake_release_tools(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_FAIL_BUILD", "1")

    with pytest.raises(subprocess.CalledProcessError):
        release_candidate(
            repository_root=repository,
            revision=revision,
            remote="origin",
            image_repository="ghcr.io/example/codex-lb",
            manifest_path=tmp_path / "candidate.json",
            cache_path=tmp_path / "cache",
            force_full=False,
            dry_run=False,
        )

    docker_config = Path((state_dir / "docker-config.txt").read_text())
    assert not docker_config.exists()
    assert not (state_dir / "trivy-calls.txt").exists()
    worktrees = _git(repository, "worktree", "list", "--porcelain")
    assert "codex-lb-release-worktree-" not in worktrees
