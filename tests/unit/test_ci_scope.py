import re
import subprocess
from pathlib import Path

from scripts.ci_scope import changed_paths, classify_paths, upstream_history_changed

REPOSITORY_ROOT = Path(__file__).parents[2]


def test_docs_only_change_needs_no_expensive_scope() -> None:
    scope = classify_paths(["docs/deployment/docker.md"])

    assert scope.level == "fast"
    assert scope.enabled_areas == ()
    assert scope.reasons == ()


def test_single_host_deploy_change_runs_only_fork_contract() -> None:
    scope = classify_paths(["deploy/single-host/deploy.py"])

    assert scope.level == "fast"
    assert scope.enabled_areas == ("fork_contract",)
    assert scope.reasons == ("single-host deployment",)


def test_single_host_deploy_test_stays_in_fork_contract_scope() -> None:
    scope = classify_paths(["tests/unit/test_single_host_deployment.py"])

    assert scope.level == "fast"
    assert scope.enabled_areas == ("fork_contract",)


def test_generic_backend_test_runs_backend_without_forcing_full_suite() -> None:
    scope = classify_paths(["tests/unit/test_auth.py"])

    assert scope.level == "fast"
    assert scope.enabled_areas == ("backend",)


def test_helm_only_change_stays_scoped_to_helm() -> None:
    scope = classify_paths(["deploy/helm/codex-lb/values.yaml"])

    assert scope.level == "fast"
    assert scope.enabled_areas == ("helm",)


def test_runtime_source_change_forces_every_area() -> None:
    scope = classify_paths(["app/main.py"])

    assert scope.level == "full"
    assert scope.enabled_areas == (
        "frontend",
        "backend",
        "helm",
        "docker",
        "migrations",
        "fork_contract",
    )
    assert scope.reasons == ("runtime source",)


def test_dependency_change_forces_every_area() -> None:
    scope = classify_paths(["pyproject.toml", "uv.lock"])

    assert scope.level == "full"
    assert scope.reasons == ("dependencies",)


def test_migration_change_forces_every_area() -> None:
    scope = classify_paths(["app/db/alembic/versions/revision.py"])

    assert scope.level == "full"
    assert scope.reasons == ("database migrations", "runtime source")


def test_explicit_full_suite_overrides_docs_only_scope() -> None:
    scope = classify_paths(["docs/deployment/docker.md"], force_full=True)

    assert scope.level == "full"
    assert len(scope.enabled_areas) == 6
    assert scope.reasons == ("explicit full-suite request",)


def test_upstream_base_change_forces_every_area() -> None:
    scope = classify_paths(["UPSTREAM_BASE"])

    assert scope.level == "full"
    assert scope.reasons == ("upstream synchronization",)


def test_integrated_upstream_history_forces_every_area_without_marker_change() -> None:
    scope = classify_paths(["docs/upstream-only.md"], upstream_sync=True)

    assert scope.level == "full"
    assert scope.reasons == ("upstream synchronization",)


def test_paths_are_normalized_and_reasons_are_deduplicated() -> None:
    scope = classify_paths(["./app/main.py", "app/modules/api_keys/api.py"])

    assert scope.level == "full"
    assert scope.reasons == ("runtime source",)


def test_recorded_upstream_base_is_a_full_sha() -> None:
    upstream_base = (REPOSITORY_ROOT / "UPSTREAM_BASE").read_text(encoding="utf-8").strip()

    assert re.fullmatch(r"[0-9a-f]{40}", upstream_base)


def test_upstream_history_change_is_detected_in_isolated_repository(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "ci-scope@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "CI Scope Test"], cwd=tmp_path, check=True)
    tracked_file = tmp_path / "tracked.txt"
    tracked_file.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    recorded_base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    upstream_base_path = tmp_path / "UPSTREAM_BASE"
    upstream_base_path.write_text(f"{recorded_base}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert upstream_history_changed(recorded_base, recorded_base, upstream_base_path) is False

    tracked_file.write_text("upstream change\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "upstream change"], cwd=tmp_path, check=True)
    upstream_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()

    assert upstream_history_changed(upstream_head, upstream_head, upstream_base_path) is True


def test_changed_paths_includes_deleted_runtime_file(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "ci-scope@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "CI Scope Test"], cwd=tmp_path, check=True)
    runtime_file = tmp_path / "app" / "deleted.py"
    runtime_file.parent.mkdir()
    runtime_file.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    runtime_file.unlink()
    subprocess.run(["git", "commit", "-qam", "delete runtime file"], cwd=tmp_path, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    monkeypatch.chdir(tmp_path)

    assert changed_paths(base, head) == ("app/deleted.py",)
