from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts import release_deploy


def _manifest(path: Path, revision: str) -> str:
    digest = "sha256:" + "a" * 64
    image = f"ghcr.io/example/codex-lb@{digest}"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repository": "ghcr.io/example/codex-lb",
                "ready": True,
                "revision": revision,
                "digest": digest,
                "image": image,
                "platform": "linux/amd64",
                "gates": {
                    "validation": {"status": "passed"},
                    "revision": {"status": "passed"},
                    "security": {"status": "passed"},
                },
            }
        ),
        encoding="utf-8",
    )
    return image


def test_release_and_deploy_runs_release_doctor_deploy_verify_and_cleanup(tmp_path: Path, monkeypatch) -> None:
    revision = "b" * 40
    manifest = tmp_path / "candidate.json"
    expected_image = f"ghcr.io/example/codex-lb@sha256:{'a' * 64}"
    commands: list[tuple[str, ...]] = []

    def fake_run(command, *, capture_output=False):
        command = tuple(command)
        commands.append(command)
        if "scripts.local_release" in command:
            _manifest(manifest, revision)
        if command[0] == "ssh" and " doctor " in command[-1]:
            detail = f"active={expected_image} previous=none running={expected_image}"
            output = json.dumps(
                {
                    "schema_version": 1,
                    "ok": True,
                    "checks": [{"name": "deployment_state", "status": "passed", "detail": detail}],
                    "deployment_state": {
                        "active_image": expected_image,
                        "previous_image": None,
                        "running_image": expected_image,
                    },
                }
            )
            return CompletedProcess(command, 0, output, "")
        return CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(release_deploy, "_run", fake_run)

    result = release_deploy.release_and_deploy(
        revision=revision,
        image_repository="ghcr.io/example/codex-lb",
        target="deploy@example.test",
        remote_repository="/opt/codex-lb",
        remote_config="/etc/codex-lb/deployment.env",
        manifest_path=manifest,
        force_full=False,
        use_sudo=True,
    )

    assert result.image == expected_image
    assert Path(commands[0][0]).name.startswith("python")
    assert [command[0] for command in commands[1:]] == ["scp", "ssh", "ssh", "ssh", "ssh"]
    assert " doctor " in commands[2][-1]
    assert " deploy " in commands[3][-1]
    assert " doctor " in commands[4][-1]
    assert "rm -f " in commands[5][-1]


def test_release_and_deploy_cleans_remote_manifest_when_doctor_fails(tmp_path: Path, monkeypatch) -> None:
    revision = "b" * 40
    manifest = tmp_path / "candidate.json"
    commands: list[tuple[str, ...]] = []

    def fake_run(command, *, capture_output=False):
        command = tuple(command)
        commands.append(command)
        if "scripts.local_release" in command:
            _manifest(manifest, revision)
        if command[0] == "ssh" and " doctor " in command[-1]:
            return CompletedProcess(
                command,
                0,
                '{"schema_version": 1, "ok": false, "checks": [], "deployment_state": null}',
                "",
            )
        return CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(release_deploy, "_run", fake_run)

    with pytest.raises(release_deploy.ReleaseDeployError, match="failed prerequisite"):
        release_deploy.release_and_deploy(
            revision=revision,
            image_repository="ghcr.io/example/codex-lb",
            target="example.test",
            remote_repository="/opt/codex-lb",
            remote_config="/etc/codex-lb/deployment.env",
            manifest_path=manifest,
            force_full=False,
            use_sudo=False,
        )

    assert "rm -f " in commands[-1][-1]


def test_final_doctor_requires_digest_as_both_active_and_running() -> None:
    expected = f"ghcr.io/example/codex-lb@sha256:{'a' * 64}"
    payload = json.dumps(
        {
            "schema_version": 1,
            "ok": True,
            "checks": [
                {
                    "name": "deployment_state",
                    "status": "passed",
                    "detail": f"active=none previous={expected} running=none",
                }
            ],
            "deployment_state": {
                "active_image": None,
                "previous_image": expected,
                "running_image": None,
            },
        }
    )

    with pytest.raises(release_deploy.ReleaseDeployError, match="deployed digest"):
        release_deploy._doctor_payload(payload, expected, final=True)
