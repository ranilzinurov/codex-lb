from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CODEX_LB_RUN_DOCKER_LIFECYCLE") != "1",
        reason="set CODEX_LB_RUN_DOCKER_LIFECYCLE=1 to run the isolated Docker lifecycle",
    ),
]


def test_single_host_docker_lifecycle_preserves_state_and_rolls_back() -> None:
    repository_root = Path(__file__).parents[2]
    result = subprocess.run(
        [sys.executable, "deploy/single-host/lifecycle_test.py", "--json"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=900,
    )

    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["initial_deploy"] == "passed"
    assert payload["successful_update"] == "passed"
    assert payload["state_preserved"] == "passed"
    assert payload["rollback"] == "passed"
    assert payload["cleanup"] == "passed"
