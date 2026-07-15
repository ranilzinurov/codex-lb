"""Run the fast contract for behavior maintained by this fork."""

from __future__ import annotations

import subprocess
from typing import Sequence

PYTEST_TARGETS = (
    "tests/unit/test_ci_scope.py",
    "tests/unit/test_ci_workflow_required_checks.py",
    "tests/unit/test_single_host_deployment.py",
    "tests/unit/test_upload_codex_usage.py",
    "tests/integration/test_external_usage_api.py",
    "tests/integration/test_accounts_api_extended.py::test_import_overwrites_for_same_account_identity_when_overwrite_enabled",
    "tests/integration/test_accounts_api_extended.py::test_import_without_overwrite_keeps_same_account_identity_on_existing_record",
    "tests/integration/test_accounts_api_extended.py::test_import_without_overwrite_keeps_different_account_identity_separate",
    "tests/integration/test_dashboard_overview.py::test_dashboard_overview_includes_estimated_api_key_attribution",
    "tests/integration/test_dashboard_overview.py::test_dashboard_overview_attribution_hides_keys_without_dashboard_opt_in",
    "tests/integration/test_dashboard_overview.py::test_dashboard_overview_attribution_uses_current_reset_window",
    "tests/integration/test_dashboard_overview.py::test_dashboard_overview_primary_attribution_includes_current_external_codex_usage",
    "tests/integration/test_proxy_images.py::test_codex_images_generations_uses_native_provider_path",
    "tests/integration/test_proxy_images.py::test_codex_images_actor_marker_does_not_replace_api_key",
)
FRONTEND_TARGETS = (
    "src/features/api-keys/components/api-key-create-dialog.test.tsx",
    "src/features/api-keys/components/api-key-edit-dialog.test.tsx",
    "src/features/api-keys/schemas.test.ts",
    "src/features/dashboard/components/account-usage-attribution.test.tsx",
    "src/features/dashboard/components/recent-requests-table.test.tsx",
)
FORK_CONTRACT_PATHS = (
    "deploy/single-host/**",
    *(target.partition("::")[0] for target in PYTEST_TARGETS),
    *(f"frontend/{target}" for target in FRONTEND_TARGETS),
)
FORK_ONLY_TEST_PATHS = tuple(target for target in PYTEST_TARGETS if "::" not in target)
PYTEST_OPTIONS = (
    "-q",
    "-ra",
    "-o",
    "faulthandler_timeout=300",
    "-o",
    "faulthandler_exit_on_timeout=true",
    "--timeout=180",
    "--timeout-method=thread",
    "--durations=20",
)


def main(argv: Sequence[str] | None = None) -> int:
    if argv:
        raise ValueError("fork-contract does not accept positional arguments")
    subprocess.run(["uv", "run", "pytest", *PYTEST_OPTIONS, *PYTEST_TARGETS], check=True)
    subprocess.run(["bun", "run", "test", "--", *FRONTEND_TARGETS], cwd="frontend", check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
