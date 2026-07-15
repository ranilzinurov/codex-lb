import re
import subprocess
from pathlib import Path

import pytest
import yaml

CI_WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "ci.yml"
MAKEFILE = Path(__file__).parents[2] / "Makefile"


def _ci_workflow_text() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


def _ci_workflow() -> dict:
    return yaml.safe_load(_ci_workflow_text())


def _job_block(text: str, job_name: str) -> str:
    start_match = re.search(rf"^  {re.escape(job_name)}:\n", text, re.MULTILINE)
    assert start_match is not None
    next_job_match = re.search(r"^  [A-Za-z0-9_-]+:\n", text[start_match.end() :], re.MULTILINE)
    if next_job_match is None:
        return text[start_match.start() :]
    return text[start_match.start() : start_match.end() + next_job_match.start()]


def test_pytest_matrix_required_contexts_are_created_for_non_backend_prs() -> None:
    test_job = _job_block(_ci_workflow_text(), "test")

    assert "name: Tests (pytest, ${{ matrix.slice.name }})" in test_job
    assert "matrix:" in test_job
    assert "\n    if: needs.changes.outputs.backend == 'true'" not in test_job
    assert "name: Skip backend tests for unrelated changes" in test_job
    assert "if: needs.changes.outputs.backend != 'true'" in test_job
    assert "required pytest context satisfied" in test_job


def test_pytest_matrix_real_test_steps_still_run_only_for_backend_changes() -> None:
    test_job = _job_block(_ci_workflow_text(), "test")

    assert "if: needs.changes.outputs.backend == 'true'\n        run: make test-${{ matrix.slice.name }}" in test_job
    for step_name in (
        "Checkout repository",
        "Set up Bun",
        "Cache Bun dependencies",
        "Set up uv",
    ):
        step = test_job.split(f"- name: {step_name}", maxsplit=1)[1]
        assert step.lstrip().startswith("if: needs.changes.outputs.backend == 'true'")


def test_postgres_required_context_is_created_for_non_backend_prs() -> None:
    pg_job = _job_block(_ci_workflow_text(), "test-postgres")

    assert "name: Tests (pytest, PostgreSQL)" in pg_job
    assert "\n    if: needs.changes.outputs.backend == 'true'" not in pg_job
    assert "name: Skip PostgreSQL tests for unrelated changes" in pg_job
    assert "if: needs.changes.outputs.backend != 'true'" in pg_job
    assert "required PostgreSQL context satisfied" in pg_job


def test_postgres_real_test_steps_still_run_only_for_backend_changes() -> None:
    pg_job = _job_block(_ci_workflow_text(), "test-postgres")

    assert "if: needs.changes.outputs.backend == 'true'\n        run: make test-postgres" in pg_job
    for step_name in (
        "Checkout repository",
        "Set up Bun",
        "Cache Bun dependencies",
        "Set up uv",
    ):
        step = pg_job.split(f"- name: {step_name}", maxsplit=1)[1]
        assert step.lstrip().startswith("if: needs.changes.outputs.backend == 'true'")


def test_docker_publish_computes_oci_digest_from_raw_manifest() -> None:
    docker_job = _job_block(_ci_workflow_text(), "docker")

    assert 'imagetools inspect "${IMAGE_TAG}" --raw > "${MANIFEST_FILE}"' in docker_job
    assert 'sha256sum "${MANIFEST_FILE}"' in docker_job
    assert "--format '{{.Digest}}'" not in docker_job


def test_change_detection_uses_one_tested_scope_classifier_for_every_event() -> None:
    workflow = _ci_workflow()
    events = workflow.get("on", workflow[True])
    outputs = workflow["jobs"]["changes"]["outputs"]

    assert {"push", "pull_request", "merge_group", "workflow_dispatch"} <= events.keys()
    assert events["workflow_dispatch"]["inputs"]["full_suite"]["default"] is True
    assert {
        "frontend",
        "backend",
        "helm",
        "docker",
        "migrations",
        "fork_contract",
        "single_host_lifecycle",
        "full_suite",
    } <= outputs.keys()


def test_fork_contract_required_context_uses_placeholder_for_unrelated_changes() -> None:
    fork_contract_job = _ci_workflow()["jobs"]["fork-contract"]
    steps = fork_contract_job["steps"]

    assert fork_contract_job["name"] == "Fork contract"
    assert "if" not in fork_contract_job
    assert any(step.get("if") == "needs.changes.outputs.fork_contract != 'true'" for step in steps)
    assert any(step.get("run") == "make fork-contract" for step in steps)
    checkout = next(step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0


def test_makefile_exposes_documented_fork_contract_target() -> None:
    result = subprocess.run(
        ["make", "--dry-run", "fork-contract"],
        cwd=MAKEFILE.parent,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_makefile_exposes_single_host_lifecycle_target() -> None:
    result = subprocess.run(
        ["make", "--dry-run", "single-host-lifecycle-test"],
        cwd=MAKEFILE.parent,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_makefile_exposes_release_deploy_operator_target() -> None:
    result = subprocess.run(
        [
            "make",
            "--dry-run",
            "release-deploy",
            "DEPLOY_HOST=deploy@example.test",
            "DEPLOY_REMOTE_REPOSITORY=/opt/codex-lb",
        ],
        cwd=MAKEFILE.parent,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "scripts.release_deploy" in result.stdout


@pytest.mark.parametrize(
    ("job_name", "scope_output"),
    (
        ("frontend-lint", "frontend"),
        ("frontend-typecheck", "frontend"),
        ("frontend-test", "frontend"),
        ("frontend-build", "frontend"),
        ("lint", "backend"),
        ("typecheck", "backend"),
        ("migration-check", "migrations"),
        ("migration-check-postgres", "migrations"),
        ("package", "backend"),
        ("docker", "docker"),
        ("single-host-lifecycle", "single_host_lifecycle"),
        ("helm-lint", "helm"),
        ("helm-smoke-kind", "helm"),
    ),
)
def test_required_jobs_use_successful_placeholders_for_unrelated_changes(
    job_name: str,
    scope_output: str,
) -> None:
    job = _ci_workflow()["jobs"][job_name]
    steps = job["steps"]

    assert job["name"]
    assert f"needs.changes.outputs.{scope_output} == 'true'" not in job.get("if", "")
    placeholder_condition = f"needs.changes.outputs.{scope_output} != 'true'"
    assert any(placeholder_condition in step.get("if", "") and step.get("run") for step in steps)
