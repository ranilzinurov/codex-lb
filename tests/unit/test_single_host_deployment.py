from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

import pytest

pytestmark = pytest.mark.unit


def _load_deploy_module():
    path = Path(__file__).parents[2] / "deploy" / "single-host" / "deploy.py"
    spec = importlib.util.spec_from_file_location("single_host_deploy", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


deploy = _load_deploy_module()


def _write_runtime_environment(path: Path, mode: int = 0o600) -> None:
    path.write_text("CODEX_LB_DATABASE_URL=sqlite+aiosqlite:////var/lib/codex-lb/store.db\n", encoding="utf-8")
    path.chmod(mode)


def _config(tmp_path: Path) -> Any:
    runtime = tmp_path / "runtime.env"
    _write_runtime_environment(runtime)
    compose = tmp_path / "compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    config = tmp_path / "deployment.env"
    config.write_text(
        "\n".join(
            (
                f"DEPLOY_RUNTIME_ENV_FILE={runtime}",
                f"DEPLOY_COMPOSE_FILE={compose}",
                f"DEPLOY_STATE_DIR={tmp_path / 'state'}",
                f"DEPLOY_BACKUP_DIR={tmp_path / 'backups'}",
                "DEPLOY_PUBLIC_READY_URL=https://proxy.example.test/health/ready",
                "DEPLOY_BACKUP_RETENTION=2",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return deploy.DeploymentConfig.from_file(config)


def _candidate(suffix: str = "a") -> Any:
    return deploy.KnownImage(
        image=f"ghcr.io/example/codex-lb@sha256:{suffix * 64}",
        revision=suffix * 40,
    )


def test_parse_candidate_requires_digest_and_revision() -> None:
    candidate = deploy.parse_candidate("ghcr.io/example/codex-lb@sha256:" + "a" * 64, "b" * 40)

    assert candidate.image.endswith("a" * 64)
    with pytest.raises(deploy.DeploymentError, match="immutable"):
        deploy.parse_candidate("ghcr.io/example/codex-lb:latest", "b" * 40)
    with pytest.raises(deploy.DeploymentError, match="revision"):
        deploy.parse_candidate(candidate.image, "not-a-revision")


def test_runtime_environment_must_not_be_group_or_world_readable(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.env"
    _write_runtime_environment(runtime, 0o644)
    compose = tmp_path / "compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    config = tmp_path / "deployment.env"
    config.write_text(
        f"DEPLOY_RUNTIME_ENV_FILE={runtime}\nDEPLOY_COMPOSE_FILE={compose}\nDEPLOY_PUBLIC_READY_URL=https://proxy.example.test/health/ready\n",
        encoding="utf-8",
    )

    with pytest.raises(deploy.DeploymentError, match="must not be accessible"):
        deploy.DeploymentConfig.from_file(config)


def test_deployment_state_round_trip_rejects_duplicate_managed_images(tmp_path: Path) -> None:
    candidate = _candidate()
    state = deploy.DeploymentState(active=candidate, managed_images=(candidate.image,))
    path = tmp_path / "state.json"

    state.write(path)

    assert deploy.DeploymentState.load(path) == state
    path.write_text(
        '{"active": null, "previous": null, "managed_images": ["' + candidate.image + '", "' + candidate.image + '"]}',
        encoding="utf-8",
    )
    with pytest.raises(deploy.DeploymentError, match="duplicate"):
        deploy.DeploymentState.load(path)

    path.write_text('{"active": {"image": "not-a-digest"}, "previous": null}', encoding="utf-8")
    with pytest.raises(deploy.DeploymentError, match="invalid active"):
        deploy.DeploymentState.load(path)


def test_disk_preflight_reports_and_rejects_insufficient_space(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config(tmp_path)
    deployment = deploy.SingleHostDeployment(config, _candidate())

    df_output = "Filesystem 1048576-blocks Used Available Capacity Mounted on\n/dev/vda 10000 9000 1000 90% /\n"
    deployment._run_command = lambda *args, **kwargs: CompletedProcess(  # type: ignore[method-assign]
        args[0], 0, df_output, ""
    )

    with pytest.raises(deploy.DeploymentError, match="required=2048MiB available=1000MiB"):
        deployment._check_free_space()
    assert "Disk preflight: required=2048MiB available=1000MiB" in capsys.readouterr().out


def test_prune_keeps_active_and_one_previous_without_touching_foreign_images(tmp_path: Path) -> None:
    config = _config(tmp_path)
    active = _candidate("a")
    previous = _candidate("b")
    historical = _candidate("c")
    foreign_image = "alpine:3.21"
    deployment = deploy.SingleHostDeployment(config, active)
    seen: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        seen.append(command)
        if command[:3] == ["docker", "ps", "--all"]:
            return CompletedProcess(command, 0, "stale-managed-container\n", "")
        if command[:3] == ["docker", "image", "rm"]:
            return CompletedProcess(command, 0, "", "")
        return CompletedProcess(command, 0, "", "")

    deployment._run_command = fake_run  # type: ignore[method-assign]
    deployment._container_metadata = lambda: {"Id": "active-managed-container"}  # type: ignore[method-assign]
    state = deploy.DeploymentState(
        active=active,
        previous=previous,
        managed_images=(active.image, previous.image, historical.image),
    )

    remaining = deployment._prune_deployment_artifacts(state)

    assert remaining == tuple(sorted((active.image, previous.image)))
    assert ["docker", "image", "rm", historical.image] in seen
    assert all(foreign_image not in command for command in seen)
    assert ["docker", "rm", "--force", "stale-managed-container"] in seen


def test_backup_retention_only_removes_deployment_owned_files(tmp_path: Path) -> None:
    config = _config(tmp_path)
    backup_dir = config.backup_dir
    backup_dir.mkdir()
    manual_backup = backup_dir / "manual.sqlite"
    manual_backup.write_bytes(b"manual")
    for index in range(3):
        path = backup_dir / f"codex-lb-deploy-20260101T00000{index}Z.sqlite"
        path.write_bytes(b"owned")
        path.touch()

    deployment = deploy.SingleHostDeployment(config, _candidate())
    deployment._prune_backups()

    assert manual_backup.exists()
    assert len(list(backup_dir.glob("codex-lb-deploy-*.sqlite"))) == 2


def test_verify_backup_checks_sqlite_integrity(tmp_path: Path) -> None:
    valid = tmp_path / "valid.sqlite"
    with sqlite3.connect(valid) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
    deploy.SingleHostDeployment._verify_backup(valid)

    invalid = tmp_path / "invalid.sqlite"
    invalid.write_text("not a sqlite database", encoding="utf-8")
    with pytest.raises(deploy.DeploymentError, match="cannot be opened"):
        deploy.SingleHostDeployment._verify_backup(invalid)


def test_backup_container_writes_as_deployment_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    config.backup_dir.mkdir()
    deployment = deploy.SingleHostDeployment(config, _candidate())
    commands: list[list[str]] = []

    monkeypatch.setattr(deploy.os, "getuid", lambda: 1001)
    monkeypatch.setattr(deploy.os, "getgid", lambda: 1002)

    def fake_run(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        del kwargs
        commands.append(command)
        if command[:3] == ["docker", "volume", "inspect"]:
            return CompletedProcess(command, 0, "[]", "")
        return CompletedProcess(command, 20, "", "")

    deployment._run_command = fake_run  # type: ignore[method-assign]

    assert deployment._backup_sqlite() is None
    docker_run = commands[1]
    user_index = docker_run.index("--user")
    assert docker_run[user_index + 1] == "1001:1002"
    volume_mount = next(argument for argument in docker_run if argument.startswith("type=volume"))
    assert volume_mount == "type=volume,src=codex-lb-data,dst=/var/lib/codex-lb"
